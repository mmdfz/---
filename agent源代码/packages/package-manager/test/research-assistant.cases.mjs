// Plain JavaScript cases exercise the shipped JavaScript payload; research-assistant.test.ts runs them.
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { buildIndex, searchIndex } from '../bundled-plugins/research-assistant/src/bm25.mjs'
import {
  defaultLibraryDir,
  frameworkRoot,
  parseConfig,
} from '../bundled-plugins/research-assistant/src/config.mjs'
import { checkPublicUrl, fetchPdf, saveDownload } from '../bundled-plugins/research-assistant/src/download.mjs'
import { judgeEvidence, parseJudgement, passes, RELATIONS } from '../bundled-plugins/research-assistant/src/judge.mjs'
import { importLibrary } from '../bundled-plugins/research-assistant/src/library.mjs'
import {
  addEvidence,
  assertCanDownload,
  finishRun,
  judgeCollectedEvidence,
  readPassage,
  recordDownload,
  runHistory,
  searchLibrary,
  startRun,
} from '../bundled-plugins/research-assistant/src/research.mjs'
import { loadManifest, statePaths } from '../bundled-plugins/research-assistant/src/store.mjs'
import { chunkPage, matchKey, tokenize } from '../bundled-plugins/research-assistant/src/text.mjs'

const publicDns = async () => [{ address: '93.184.216.34', family: 4 }]
const noSleep = async () => {}
const reply = (content, status = 200) =>
  new Response(JSON.stringify({ choices: [{ message: { content } }] }), { status })

let dir
beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'agnes-research-'))
})
afterEach(async () => {
  await rm(dir, { recursive: true, force: true })
})

const configFor = (threshold) =>
  parseConfig({
    libraryDir: dir,
    jev: { baseUrl: 'https://jev.test/v1/', model: 'jev-small', ...(threshold === undefined ? {} : { threshold }) },
  })

describe('text processing', () => {
  it('matches quotes across hyphenation, line breaks and spacing', () => {
    expect(matchKey('the evi-\ndence  clearly shows')).toBe(matchKey('the evidence clearly shows'))
    expect(matchKey('self-\nreported')).toBe(matchKey('self-reported'))
  })

  it('stems inflections to one term', () => {
    expect(new Set(tokenize('measured measures measuring measure')).size).toBe(1)
  })

  it('splits pages into paragraphs and carries the section across pages', () => {
    const long = 'Participants completed the task under controlled laboratory conditions every morning'
    const first = chunkPage({
      docId: 'd1',
      page: 3,
      text: `2 Methods\n${long} and evening\nacross two weeks of testing.\n${long}.`,
    })
    expect(first.section).toBe('2 Methods')
    expect(first.chunks.every((chunk) => chunk.page === 3 && chunk.section === '2 Methods')).toBe(true)
    const next = chunkPage({ docId: 'd1', page: 4, text: `${long} again.`, section: first.section })
    expect(next.chunks[0].section).toBe('2 Methods')
  })
})

describe('BM25 retrieval', () => {
  const chunks = [
    { id: 'a', text: 'Sleep deprivation reduces working memory accuracy in adults.' },
    { id: 'b', text: 'Caffeine intake was recorded for all participants.' },
    { id: 'c', text: 'Working memory was assessed with an n-back task.' },
  ]
  it('ranks the passage matching most query terms first and reports coverage', () => {
    const { hits } = searchIndex(buildIndex(chunks), 'sleep deprivation working memory')
    expect(hits[0].chunk.id).toBe('a')
    expect(hits[0].coverage).toBe(1)
    expect(hits.map((hit) => hit.chunk.id)).not.toContain('b')
  })
  it('skips excluded passages', () => {
    const { hits } = searchIndex(buildIndex(chunks), 'working memory', { exclude: new Set(['a']) })
    expect(hits.map((hit) => hit.chunk.id)).toEqual(['c'])
  })
})

describe('configuration', () => {
  it('defaults the Jev threshold to 0.9', async () => {
    expect((await configFor()).jev).toMatchObject({ threshold: 0.9, baseUrl: 'https://jev.test/v1' })
  })
  it('defaults the library to the paper folder of the framework that runs AGH', async () => {
    const entry = join(dir, 'packages', 'cli', 'dist', 'local', 'daemon.mjs')
    await mkdir(join(dir, 'packages', 'cli'), { recursive: true })
    await writeFile(join(dir, 'package.json'), JSON.stringify({ name: 'agnes-harness' }))
    await writeFile(join(dir, 'packages', 'cli', 'package.json'), JSON.stringify({ name: '@agnes/cli' }))
    expect(await frameworkRoot(entry)).toBe(dir)
    const config = await parseConfig(
      { jev: { baseUrl: 'https://jev.test/v1', model: 'jev-small' } },
      '<config>',
      { defaultLibrary: () => defaultLibraryDir(entry) },
    )
    expect(config.libraryDir).toBe(await realpath(join(dir, 'paper')))
    expect(existsSync(join(dir, 'paper'))).toBe(true)
  })
  it.each([
    [{ libraryDir: 'relative/papers', jev: { baseUrl: 'https://x/v1', model: 'm' } }],
    [{ libraryDir: '__dir__', jev: { baseUrl: 'https://x/v1' } }],
    [{ libraryDir: '__dir__', jev: { baseUrl: 'https://x/v1', model: 'm', threshold: 1.5 } }],
    [{ libraryDir: '__dir__', jev: { baseUrl: 'ftp://x', model: 'm' } }],
    [{ libraryDir: '__dir__', jev: { baseUrl: 'https://x/v1', model: 'm', api: 'completions' } }],
  ])('rejects invalid config %#', async (raw) => {
    const value = JSON.parse(JSON.stringify(raw).replace('__dir__', dir.replaceAll('\\', '\\\\')))
    await expect(parseConfig(value)).rejects.toMatchObject({ code: 'RESEARCH_CONFIG_INVALID' })
  })
})

describe('Jev evidence judge', () => {
  const jev = { baseUrl: 'https://jev.test/v1', apiKey: 'k', model: 'jev-small', threshold: 0.9 }
  const input = { question: 'q', proposedAnswer: 'a', quote: 'quote', source: { document: 'd' } }

  it('parses fenced JSON and sends one pair with the bearer key', async () => {
    const calls = []
    const result = await judgeEvidence(jev, input, {
      sleep: noSleep,
      fetchImpl: async (url, init) => {
        calls.push([url, init])
        return reply('```json\n{"relation":"supports","confidence":0.93,"explanation":"direct"}\n```')
      },
    })
    expect(result).toMatchObject({ relation: 'supports', confidence: 0.93 })
    expect(calls[0][0]).toBe('https://jev.test/v1/chat/completions')
    expect(calls[0][1].headers.authorization).toBe('Bearer k')
  })

  it('asks the Decisions API one relation choice and gates on the weaker signal', async () => {
    const decisions = { ...jev, api: 'decisions', model: 'typesafe/jev-1.13' }
    const calls = []
    const answer = (probability, confidence) =>
      new Response(
        JSON.stringify({
          model: 'typesafe/jev-1.13',
          answers: {
            relation: {
              type: 'choice',
              choice: 'supports',
              probabilities: { supports: probability, insufficient: 1 - probability },
              confidence,
            },
          },
        }),
      )
    const strong = await judgeEvidence(decisions, input, {
      sleep: noSleep,
      fetchImpl: async (url, init) => {
        calls.push([url, init])
        return answer(0.96, 0.93)
      },
    })
    expect(calls[0][0]).toBe('https://jev.test/v1/decisions')
    expect(calls[0][1].headers.authorization).toBe('Bearer k')
    const sent = JSON.parse(calls[0][1].body)
    expect(sent).toMatchObject({ model: 'typesafe/jev-1.13', state: { evidence_excerpt: 'quote' } })
    expect(Object.keys(sent.questions.relation.criteria)).toEqual([...RELATIONS])
    expect(strong).toMatchObject({ relation: 'supports', confidence: 0.93 })
    expect(passes(strong, 0.9)).toBe(true)
    const pooled = []
    await judgeEvidence(
      decisions,
      {
        question: 'q',
        proposedAnswer: 'a',
        evidence: [
          { id: 'e1', quote: 'one', document: 'a.pdf' },
          { id: 'e2', quote: 'two', document: 'b.pdf' },
        ],
      },
      {
        sleep: noSleep,
        fetchImpl: async (_url, init) => {
          pooled.push(JSON.parse(init.body))
          return answer(0.97, 0.96)
        },
      },
    )
    expect(pooled).toHaveLength(1)
    expect(pooled[0].state.evidence).toHaveLength(2)
    expect(pooled[0].state.evidence_excerpt).toBeUndefined()
    expect(Object.keys(pooled[0].questions)).toEqual(['relation'])
    expect(pooled[0].questions.relation.instructions).toMatch(/together/)
    const weak = await judgeEvidence(decisions, input, { sleep: noSleep, fetchImpl: async () => answer(0.84, 0.95) })
    expect(passes(weak, 0.9)).toBe(false)
    await expect(
      judgeEvidence(decisions, input, { sleep: noSleep, fetchImpl: async () => reply('{"relation":"supports"}') }),
    ).rejects.toMatchObject({ code: 'JUDGE_UNAVAILABLE' })
  })

  it('retries malformed output, then fails closed as unavailable', async () => {
    let count = 0
    const fetchImpl = async () => {
      count++
      return reply('I think it supports it.')
    }
    await expect(judgeEvidence(jev, input, { fetchImpl, sleep: noSleep })).rejects.toMatchObject({
      code: 'JUDGE_UNAVAILABLE',
    })
    expect(count).toBe(3)
  })

  it('does not retry an authentication failure', async () => {
    let count = 0
    const fetchImpl = async () => {
      count++
      return new Response('denied', { status: 401 })
    }
    await expect(judgeEvidence(jev, input, { fetchImpl, sleep: noSleep })).rejects.toMatchObject({
      code: 'JUDGE_UNAVAILABLE',
    })
    expect(count).toBe(1)
  })

  it('passes only decisive relations at or above the threshold', () => {
    expect(passes({ relation: 'supports', confidence: 0.9 }, 0.9)).toBe(true)
    expect(passes({ relation: 'supports', confidence: 0.89 }, 0.9)).toBe(false)
    expect(passes({ relation: 'insufficient', confidence: 1 }, 0.9)).toBe(false)
    expect(parseJudgement('{"relation":"proven","confidence":1}')).toBeUndefined()
    expect(parseJudgement('{"relation":"supports","confidence":2}')).toBeUndefined()
  })
})

describe('controlled PDF download', () => {
  const pdf = Buffer.from('%PDF-1.7\n1 0 obj <<>> endobj\n%%EOF')

  it.each([
    ['http://example.org/a.pdf'],
    ['https://user:pw@example.org/a.pdf'],
    ['https://127.0.0.1/a.pdf'],
    ['https://[::1]/a.pdf'],
  ])('rejects %s', async (url) => {
    await expect(checkPublicUrl(new URL(url), publicDns)).rejects.toMatchObject({ code: 'DOWNLOAD_REJECTED' })
  })

  it('rejects hosts that resolve to private addresses', async () => {
    const privateDns = async () => [{ address: '10.0.0.5', family: 4 }]
    await expect(checkPublicUrl(new URL('https://repo.example.org/a.pdf'), privateDns)).rejects.toMatchObject({
      code: 'DOWNLOAD_REJECTED',
    })
  })

  it('re-validates every redirect target', async () => {
    const fetchImpl = async () =>
      new Response(null, { status: 302, headers: { location: 'https://169.254.169.254/latest' } })
    await expect(
      fetchPdf('https://repo.example.org/a.pdf', { fetchImpl, resolve: publicDns }),
    ).rejects.toMatchObject({ code: 'DOWNLOAD_REJECTED' })
  })

  it.each([
    [403, 'DOWNLOAD_ACCESS_DENIED'],
    [200, 'DOWNLOAD_NOT_PDF'],
  ])('reports HTTP %i landing pages as %s', async (status, code) => {
    const fetchImpl = async () =>
      new Response('<html>Sign in</html>', { status, headers: { 'content-type': 'text/html' } })
    await expect(
      fetchPdf('https://publisher.example.org/a.pdf', { fetchImpl, resolve: publicDns }),
    ).rejects.toMatchObject({ code })
  })

  it('saves a verified PDF once into downloads with its source metadata', async () => {
    const config = await configFor()
    const fetched = await fetchPdf('https://arxiv.org/pdf/2401.00001', {
      fetchImpl: async () => new Response(pdf, { headers: { 'content-type': 'application/pdf' } }),
      resolve: publicDns,
    })
    const meta = { url: 'https://arxiv.org/pdf/2401.00001', title: 'Sleep and Memory: A Study', doi: '10.1/x' }
    const first = await saveDownload(config, fetched, meta)
    const second = await saveDownload(config, fetched, meta)
    expect(first.relPath).toBe('downloads/Sleep_and_Memory_A_Study.pdf')
    expect(existsSync(join(dir, first.relPath))).toBe(true)
    expect(second).toMatchObject({ relPath: first.relPath, alreadyPresent: true })
    const manifest = await loadManifest(statePaths(config))
    expect(manifest.sources[first.sha256]).toMatchObject({ doi: '10.1/x', acquisition: 'full_text' })
  })
})

describe('local library to judged evidence', () => {
  const quote = 'Participants who slept fewer than six hours showed a 23 percent reduction in working memory accuracy'

  beforeEach(async () => {
    await mkdir(join(dir, 'papers'))
    await writeFile(
      join(dir, 'papers', 'sleep.md'),
      `# Results\n\n${quote} compared with the control group of well-rested adults.\n\nThe effect was observed only in adults older than 40 years, and not in younger participants of the cohort.\n`,
    )
    await writeFile(join(dir, 'papers', 'data.xlsx'), 'PK')
    await writeFile(join(dir, 'papers', 'fake.pdf'), 'not really a pdf')
  })

  const importNow = async (config) =>
    importLibrary(config, { deadline: Date.now() + 60_000, signal: new AbortController().signal })

  it('indexes supported files and reports unsupported ones with a reason', async () => {
    const config = await configFor()
    const { manifest } = await importNow(config)
    const docs = Object.values(manifest.documents)
    expect(docs.map((doc) => [doc.displayName, doc.status])).toEqual([['sleep.md', 'indexed']])
    expect(manifest.files['papers/data.xlsx'].status).toBe('unsupported')
    expect(manifest.files['papers/fake.pdf']).toMatchObject({ status: 'unsupported' })
    const again = await importNow(config)
    expect(again.processed).toEqual([])
  })

  it('verifies quotes, then judges the verified set once', async () => {
    const config = await configFor()
    await importNow(config)
    const { run } = await startRun(config, { question: 'Does short sleep impair working memory?' })
    expect((await startRun(config, { question: 'does short sleep  impair working memory?' })).resumed).toBe(true)

    const found = await searchLibrary(config, { runId: run.runId, query: 'slept hours working memory accuracy' })
    expect(found.localSufficient).toBe(true)
    expect(found.hits[0]).toMatchObject({ document: 'sleep.md', section: 'Results' })
    const repeat = await searchLibrary(config, { runId: run.runId, query: 'slept hours working memory accuracy' })
    expect(repeat.hits.length).toBeLessThan(found.hits.length)
    await expect(finishRun(config, { runId: run.runId, outcome: 'answered' })).rejects.toMatchObject({
      code: 'RESEARCH_EVIDENCE_REQUIRED',
    })

    const base = {
      runId: run.runId,
      chunkId: found.hits[0].chunkId,
      question: 'Does short sleep impair working memory?',
      proposedAnswer: 'Yes, by about 23 percent.',
    }
    const scope = 'The effect was observed only in adults older than 40 years, and not in younger participants of the cohort.'
    const first = await addEvidence(config, { ...base, quote })
    const second = await addEvidence(config, { ...base, quote: scope })
    expect(first.record).toMatchObject({ verification: 'verified', passed: false })
    expect(second.record.verification).toBe('verified')
    const paraphrase = await addEvidence(config, {
      ...base,
      quote: 'Short sleepers lost nearly a quarter of their working memory accuracy',
    })
    expect(paraphrase.record).toMatchObject({ verification: 'location_failed', passed: false })

    let seen = []
    const judge = (relation, confidence) => async (_jev, input) => {
      seen = input.evidence
      return { relation, confidence, explanation: 'direct', judgeVersion: 'jev-small@test' }
    }
    const weak = await judgeCollectedEvidence(
      config,
      { runId: run.runId, proposedAnswer: 'Yes, by about 23 percent.' },
      { judge: judge('supports', 0.85) },
    )
    expect(seen.map((item) => item.id)).toEqual(['e1', 'e2'])
    expect(weak.judgement).toMatchObject({ passed: false, relation: 'supports', evidenceIds: ['e1', 'e2'] })
    await expect(finishRun(config, { runId: run.runId, outcome: 'answered' })).rejects.toMatchObject({
      code: 'RESEARCH_EVIDENCE_REQUIRED',
    })
    const broken = await judgeCollectedEvidence(
      config,
      { runId: run.runId, proposedAnswer: 'Yes, by about 23 percent.' },
      {
        judge: async () => {
          throw Object.assign(new Error('down'), { code: 'JUDGE_UNAVAILABLE' })
        },
      },
    )
    expect(broken.judgement).toMatchObject({ judge: 'judge_unavailable', passed: false })
    await expect(finishRun(config, { runId: run.runId, outcome: 'conflict' })).rejects.toMatchObject({
      code: 'RESEARCH_EVIDENCE_REQUIRED',
    })
    await judgeCollectedEvidence(
      config,
      { runId: run.runId, proposedAnswer: 'Yes, by about 23 percent.' },
      { judge: judge('supports', 0.95) },
    )
    await expect(finishRun(config, { runId: run.runId, outcome: 'conflict' })).rejects.toMatchObject({
      code: 'RESEARCH_EVIDENCE_REQUIRED',
    })
    await addEvidence(config, { ...base, quote: scope })
    await expect(finishRun(config, { runId: run.runId, outcome: 'answered' })).rejects.toMatchObject({
      code: 'RESEARCH_EVIDENCE_REQUIRED',
    })
    await judgeCollectedEvidence(
      config,
      { runId: run.runId, proposedAnswer: 'Yes, by about 23 percent, in adults older than 40.' },
      { judge: judge('supports', 0.95) },
    )
    expect(seen).toHaveLength(3)

    const summary = await finishRun(config, { runId: run.runId, outcome: 'answered' })
    expect(summary.judgement).toMatchObject({ relation: 'supports', confidence: 0.95, passed: true })
    expect(summary.evidence[0]).toMatchObject({ id: 'e1', file: 'papers/sleep.md' })
    await expect(addEvidence(config, { ...base, quote })).rejects.toMatchObject({ code: 'RESEARCH_RUN_FINISHED' })
  })

  it('keeps earlier questions of a conversation for reuse and judges reused quotes again', async () => {
    const config = await configFor()
    await importNow(config)
    const supports = (confidence) => async () => ({
      relation: 'supports',
      confidence,
      explanation: 'round',
      judgeVersion: 'jev-small@test',
    })
    const a = await startRun(
      config,
      { question: 'Does short sleep impair working memory?' },
      { session: 'chat-1' },
    )
    expect(a.history).toEqual([])
    const [hit] = (await searchLibrary(config, { runId: a.run.runId, query: 'slept hours working memory' })).hits
    const first = { runId: a.run.runId, chunkId: hit.chunkId, quote, proposedAnswer: 'Yes.' }
    await addEvidence(config, { ...first, question: 'Does short sleep impair working memory?' })
    await judgeCollectedEvidence(
      config,
      { runId: a.run.runId, proposedAnswer: 'Yes.' },
      { judge: supports(0.95) },
    )
    await finishRun(config, { runId: a.run.runId, outcome: 'answered' })

    const other = await startRun(config, { question: 'Unrelated chat question' }, { session: 'chat-2' })
    expect(other.history).toEqual([])
    const c = await startRun(config, { question: 'How large is the working memory effect?' }, { session: 'chat-1' })
    expect(c.history).toEqual([
      expect.objectContaining({ runId: a.run.runId, outcome: 'answered', documents: ['sleep.md'], passed: 1 }),
    ])
    const [prior] = (await runHistory(config, { runId: c.run.runId })).runs[0].evidence
    expect(prior).toMatchObject({ ref: `${a.run.runId}/e1`, chunkId: hit.chunkId, quote, passed: true })

    const reused = await addEvidence(config, {
      runId: c.run.runId,
      chunkId: prior.chunkId,
      quote: prior.quote,
      question: 'How large is the working memory effect?',
      proposedAnswer: 'About 23 percent.',
      reusedFrom: prior.ref,
    })
    expect(reused.record).toMatchObject({
      passed: false,
      reusedFrom: { runId: a.run.runId, evidenceId: 'e1' },
    })
    const again = await judgeCollectedEvidence(
      config,
      { runId: c.run.runId, proposedAnswer: 'About 23 percent.' },
      { judge: supports(0.5) },
    )
    expect(again.judgement).toMatchObject({ passed: false, evidenceIds: ['e1'] })
    await expect(
      addEvidence(config, { ...first, runId: other.run.runId, question: 'q?', reusedFrom: prior.ref }),
    ).rejects.toMatchObject({ code: 'RESEARCH_REUSE_UNKNOWN' })
  })

  it('reads one local paper at most three times and caps retrieved papers and evidence', async () => {
    const config = await configFor()
    await importNow(config)
    const { run } = await startRun(config, { question: 'Does short sleep impair working memory?' })
    const [hit] = (await searchLibrary(config, { runId: run.runId, query: 'slept hours working memory' })).hits
    for (let time = 0; time < 3; time++) await readPassage(config, { chunkId: hit.chunkId, runId: run.runId })
    await expect(readPassage(config, { chunkId: hit.chunkId, runId: run.runId })).rejects.toMatchObject({
      code: 'RESEARCH_PAPER_REVIEW_LIMIT',
    })
    await recordDownload(config, run.runId, {
      ok: true,
      url: 'https://example.org/a.pdf',
      relPath: 'downloads/a.pdf',
      docId: hit.docId,
    })
    const pair = {
      runId: run.runId,
      chunkId: hit.chunkId,
      quote,
      question: 'Does short sleep impair working memory?',
      proposedAnswer: 'Not shown.',
    }
    for (let item = 0; item < 10; item++) await addEvidence(config, pair)
    await expect(addEvidence(config, pair)).rejects.toMatchObject({ code: 'RESEARCH_EXTERNAL_LIMIT' })
    for (let paper = 0; paper < 4; paper++)
      await recordDownload(config, run.runId, {
        ok: true,
        url: `https://example.org/${paper}.pdf`,
        relPath: `downloads/${paper}.pdf`,
        docId: `other-${paper}`,
      })
    await expect(assertCanDownload(config, run.runId)).rejects.toMatchObject({ code: 'RESEARCH_EXTERNAL_LIMIT' })
  })
})
