const STOPWORDS = new Set(
  (
    'a about above after again against all also am an and any are as at be because been before being ' +
    'below between both but by can could did do does doing down during each few for from further had has ' +
    'have having he her here hers herself him himself his how however i if in into is it its itself just ' +
    'may me might more most must my myself no nor not now of off on once only or other our ours ourselves ' +
    'out over own same shall she should so some such than that the their theirs them themselves then there ' +
    'therefore these they this those through thus to too under until up upon very was we were what when ' +
    'where whether which while who whom why will with within without would yet you your yours et al'
  ).split(' '),
)

const SUFFIXES = [
  ['ational', 'ate'],
  ['ization', 'ize'],
  ['iveness', 'ive'],
  ['fulness', 'ful'],
  ['ousness', 'ous'],
  ['ies', 'y'],
  ['ing', ''],
  ['ed', ''],
  ['ly', ''],
]

/** A deliberately small English stemmer: reproducible and good enough for keyword retrieval. */
export function stem(word) {
  if (word.length <= 3 || /\d/u.test(word)) return word
  let w = word
  for (const [suffix, replacement] of SUFFIXES)
    if (w.endsWith(suffix) && w.length - suffix.length >= 3) {
      w = w.slice(0, -suffix.length) + replacement
      break
    }
  if (w === word && w.endsWith('s') && !/[sui]s$/u.test(w) && w.length > 4) w = w.slice(0, -1)
  if (/([b-df-hj-km-np-tv-xz])\1$/u.test(w) && !/(ll|ss|zz)$/u.test(w)) w = w.slice(0, -1)
  if (w.endsWith('e') && w.length > 4) w = w.slice(0, -1)
  return w
}

export function tokenize(text) {
  const tokens = []
  for (const raw of text.normalize('NFKC').toLowerCase().split(/[^\p{L}\p{N}]+/u)) {
    if (raw.length < 2 || STOPWORDS.has(raw)) continue
    tokens.push(stem(raw))
  }
  return tokens
}

/** Letters and digits only: a quote matches across line breaks, hyphenation and spacing differences. */
export function matchKey(text) {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '')
}

export const MIN_QUOTE_KEY_LENGTH = 20

const NAMED_HEADING =
  /^(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|introduction|background|related work|literature review|methods?|materials and methods|methodology|study design|experiments?|experimental setup|results?|findings|discussion|general discussion|conclusions?|limitations|future work|references|bibliography|acknowledge?ments?|appendix(?: [a-z])?|supplementary materials?)\.?$/iu
const NUMBERED_HEADING = /^\d{1,2}(?:\.\d{1,2})*\.?\s+\p{Lu}[\p{L}\s,:&()-]{2,70}$/u

export function headingOf(line) {
  const trimmed = line.trim().replace(/^#{1,6}\s+/u, '')
  if (trimmed.length > 80 || /[.?!;]$/u.test(trimmed)) return undefined
  return NAMED_HEADING.test(trimmed) || NUMBERED_HEADING.test(trimmed) ? trimmed : undefined
}

function cleanLines(text) {
  return text
    .replace(/\r\n?/gu, '\n')
    .replace(/\u00ad/gu, '')
    .replace(/[ \t\f\v\u00a0]+/gu, ' ')
    .split('\n')
    .map((line) => line.trim())
}

function median(values) {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)]
}

function joinLines(lines) {
  let out = ''
  for (const line of lines) {
    if (!out) out = line
    else if (/\p{L}-$/u.test(out) && /^\p{Ll}/u.test(line)) out = out.slice(0, -1) + line
    else out += ` ${line}`
  }
  return out
}

/**
 * Split one page of extracted text into paragraphs. PDF text layers rarely keep blank lines, so a
 * short line ending a sentence also closes a paragraph. Headings update the running section.
 */
export function pageParagraphs(text, section) {
  const lines = cleanLines(text)
  const typical = median(lines.filter((line) => line.length > 20).map((line) => line.length))
  const paragraphs = []
  let current = [],
    currentSection = section
  const flush = () => {
    if (current.length) paragraphs.push({ text: joinLines(current), section: currentSection })
    current = []
  }
  for (const line of lines) {
    if (!line) {
      flush()
      continue
    }
    const heading = headingOf(line)
    if (heading) {
      // The heading text stays in the next paragraph, so a misdetected heading loses no content.
      flush()
      currentSection = heading
    }
    current.push(line)
    if (/[.?!:]["')\]]?$/u.test(line) && typical && line.length < 0.8 * typical) flush()
  }
  flush()
  return { paragraphs, section: currentSection }
}

const TARGET = 1200,
  MAX = 1600,
  MIN = 120

function splitLong(text) {
  if (text.length <= MAX) return [text]
  const sentences = text.match(/[^.?!]+(?:[.?!]+["')\]]?\s*|$)/gu) ?? [text]
  const pieces = []
  let current = ''
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > TARGET) {
      pieces.push(current.trim())
      current = ''
    }
    current += sentence
    while (current.length > MAX) {
      pieces.push(current.slice(0, TARGET).trim())
      current = current.slice(TARGET)
    }
  }
  if (current.trim()) pieces.push(current.trim())
  return pieces
}

/** Chunks keep their page and paragraph position; tiny fragments merge into the following paragraph. */
export function chunkPage({ docId, page, text, section }) {
  const { paragraphs, section: nextSection } = pageParagraphs(text, section)
  const chunks = []
  let carry
  paragraphs.forEach((paragraph, index) => {
    const merged = carry
      ? { text: `${carry.text} ${paragraph.text}`, section: carry.section, paragraph: carry.paragraph }
      : { ...paragraph, paragraph: index + 1 }
    carry = undefined
    if (merged.text.length < MIN && index < paragraphs.length - 1) {
      carry = merged
      return
    }
    for (const piece of splitLong(merged.text))
      chunks.push({
        id: `${docId}:${page ?? 0}:${chunks.length + 1}`,
        page,
        paragraph: merged.paragraph,
        ...(merged.section ? { section: merged.section } : {}),
        text: piece,
      })
  })
  return { chunks, section: nextSection }
}
