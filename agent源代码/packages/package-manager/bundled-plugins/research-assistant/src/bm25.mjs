import { tokenize } from './text.mjs'

const K1 = 1.2,
  B = 0.75

export function buildIndex(chunks) {
  const postings = new Map()
  const lengths = []
  chunks.forEach((chunk, position) => {
    const counts = new Map()
    const tokens = tokenize(chunk.text)
    for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1)
    lengths.push(tokens.length)
    for (const [term, tf] of counts) {
      let list = postings.get(term)
      if (!list) postings.set(term, (list = []))
      list.push([position, tf])
    }
  })
  const total = lengths.reduce((sum, length) => sum + length, 0)
  return { chunks, postings, lengths, averageLength: chunks.length ? total / chunks.length : 0 }
}

/** BM25 ranking; coverage is the share of distinct query terms a hit contains. */
export function searchIndex(index, query, { limit = 8, exclude } = {}) {
  const terms = [...new Set(tokenize(query))]
  if (!terms.length || !index.chunks.length) return { terms, hits: [] }
  const n = index.chunks.length
  const scores = new Map()
  const matched = new Map()
  for (const term of terms) {
    const list = index.postings.get(term)
    if (!list) continue
    const idf = Math.log(1 + (n - list.length + 0.5) / (list.length + 0.5))
    for (const [position, tf] of list) {
      if (exclude?.has(index.chunks[position].id)) continue
      const norm = tf + K1 * (1 - B + (B * index.lengths[position]) / (index.averageLength || 1))
      scores.set(position, (scores.get(position) ?? 0) + (idf * (tf * (K1 + 1))) / norm)
      let set = matched.get(position)
      if (!set) matched.set(position, (set = new Set()))
      set.add(term)
    }
  }
  const hits = [...scores]
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .slice(0, limit)
    .map(([position, score]) => ({
      chunk: index.chunks[position],
      score,
      coverage: matched.get(position).size / terms.length,
    }))
  return { terms, hits }
}
