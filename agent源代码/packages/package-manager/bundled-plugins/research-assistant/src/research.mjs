import { randomBytes } from 'node:crypto'
import { readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { searchIndex } from './bm25.mjs'
import { describeError, fail } from './errors.mjs'
import { judgeEvidence, passes } from './judge.mjs'
import { libraryIndex } from './library.mjs'
import { readJson, runPath, statePaths, withLock, writeJsonAtomic } from './store.mjs'
import { MIN_QUOTE_KEY_LENGTH, matchKey } from './text.mjs'

export const LOCAL_MIN_COVERAGE = 0.6
/** A local paper may be read this many times in one question; further reads are refused. */
export const LOCAL_PAPER_REVIEW_LIMIT = 3
/** Papers downloaded for one question, and evidence taken from those papers. */
export const EXTERNAL_PAPER_LIMIT = 5
export const EXTERNAL_EVIDENCE_LIMIT = 10
const HIT_TEXT_CHARS = 1500
const CONTEXT_CHARS = 700

export const OUTCOMES = Object.freeze([
  'answered',
  'insufficient',
  'conflict',
  'acquisition_unavailable',
  'failed',
  'cancelled',
])
export const LOG_STAGES = Object.freeze([
  'mcp_search',
  'candidate_selected',
  'fulltext_check',
  'acquisition_unavailable',
  'external_search_unavailable',
  'note',
])

const now = () => new Date().toISOString()
const clip = (text, max) => (text.length > max ? `${text.slice(0, max)}…` : text)

function transition(run, state, note) {
  run.state = state
  run.updatedAt = now()
  run.events.push({ at: run.updatedAt, state, ...(note ? { note: clip(note, 400) } : {}) })
}

async function loadRun(config, runId) {
  if (typeof runId !== 'string' || !/^r-[0-9a-z-]{8,64}$/u.test(runId))
    throw fail('RESEARCH_RUN_INVALID', 'Unknown runId. Call research_start first.')
  const run = await readJson(runPath(statePaths(config), runId), undefined)
  if (!run) throw fail('RESEARCH_RUN_NOT_FOUND', `Run ${runId} does not exist.`)
  return run
}

/** Mutate one run under the library lock and persist it before returning. */
export function updateRun(config, runId, mutate) {
  return withLock(config.stateDir, async () => {
    const run = await loadRun(config, runId)
    const result = await mutate(run)
    await writeJsonAtomic(runPath(statePaths(config), runId), run)
    return result
  })
}

export const getRun = loadRun

const normalizeQuestion = (text) => text.normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim()

async function allRuns(paths) {
  const names = await readdir(paths.runs).catch(() => [])
  const runs = []
  for (const name of names.filter((n) => n.endsWith('.json')).sort()) {
    const run = await readJson(join(paths.runs, name), undefined)
    if (run) runs.push(run)
  }
  return runs.sort((a, b) => a.createdAt.localeCompare(b.createdAt))
}

const HISTORY_RUNS = 10
const HISTORY_EVIDENCE = 20

/** Earlier runs of the same conversation, oldest first; runs without a session are never shared. */
async function earlierRuns(config, session, excludeRunId) {
  if (!session) return []
  const runs = await allRuns(statePaths(config))
  return runs.filter((run) => run.session === session && run.runId !== excludeRunId).slice(-HISTORY_RUNS)
}

function roundPassedIds(run) {
  if (run.judgement) return new Set(run.judgement.passed ? (run.judgement.evidenceIds ?? []) : [])
  return new Set(run.evidence.filter((record) => record.passed).map((record) => record.evidenceId))
}

function historyRun(run, { withEvidence }) {
  const verified = run.evidence.filter((record) => record.verification === 'verified')
  const passedIds = roundPassedIds(run)
  const view = {
    runId: run.runId,
    question: run.question,
    outcome: run.outcome ?? null,
    documents: [...new Set(run.evidence.map((record) => record.document))],
    evidence: verified.length,
    passed: verified.filter((record) => passedIds.has(record.evidenceId)).length,
  }
  if (!withEvidence) return view
  return {
    ...view,
    evidence: [...verified]
      .sort((a, b) => Number(passedIds.has(b.evidenceId)) - Number(passedIds.has(a.evidenceId)))
      .slice(0, HISTORY_EVIDENCE)
      .map((record) => ({
        ref: `${run.runId}/${record.evidenceId}`,
        chunkId: record.chunkId,
        document: record.document,
        ...record.location,
        quote: record.quote,
        question: record.question,
        relation: run.judgement?.relation ?? null,
        confidence: run.judgement?.confidence ?? null,
        passed: passedIds.has(record.evidenceId),
      })),
  }
}

/**
 * Papers and verified quotes from earlier questions in this conversation. Reusing one means adding
 * it to the current run with research_add_evidence; the new question judges its whole set again.
 */
export async function runHistory(config, { runId }) {
  const run = await loadRun(config, runId)
  return { runs: (await earlierRuns(config, run.session, run.runId)).map((r) => historyRun(r, { withEvidence: true })) }
}

/** A repeated question resumes its open run in the same conversation rather than starting a duplicate. */
export function startRun(config, { question, claims }, { session } = {}) {
  return withLock(config.stateDir, async () => {
    const paths = statePaths(config)
    const key = normalizeQuestion(question)
    const history = async (run) =>
      (await earlierRuns(config, session, run.runId)).map((r) => historyRun(r, { withEvidence: false }))
    for (const run of (await allRuns(paths)).reverse())
      if (!run.outcome && run.session === session && normalizeQuestion(run.question) === key)
        return { run, resumed: true, history: await history(run) }
    const createdAt = now()
    const runId = `r-${createdAt.slice(0, 10).replaceAll('-', '')}-${randomBytes(4).toString('hex')}`
    const run = {
      runId,
      ...(session ? { session } : {}),
      question,
      normalizedClaims: (claims?.length ? claims : [question]).map((text, index) => ({
        id: `c${index + 1}`,
        text,
      })),
      state: 'created',
      createdAt,
      updatedAt: createdAt,
      events: [{ at: createdAt, state: 'created' }],
      searches: [],
      examinedChunks: [],
      paperReviews: {},
      logs: [],
      downloads: [],
      evidence: [],
    }
    transition(run, 'question_parsed')
    await writeJsonAtomic(runPath(paths, runId), run)
    return { run, resumed: false, history: await history(run) }
  })
}

function hitView(entry, score, coverage) {
  const { chunk, doc } = entry
  return {
    chunkId: chunk.id,
    document: doc.displayName,
    docId: doc.docId,
    ...(chunk.page ? { page: chunk.page } : {}),
    paragraph: chunk.paragraph,
    ...(chunk.section ? { section: chunk.section } : {}),
    ...(doc.ocrPages?.includes(chunk.page) ? { ocr: true } : {}),
    acquisition: doc.acquisition,
    score: Math.round(score * 100) / 100,
    coverage: Math.round(coverage * 100) / 100,
    text: clip(chunk.text, HIT_TEXT_CHARS),
  }
}

export async function searchLibrary(config, { runId, query, limit = 8, includeExamined = false }) {
  const { index, byId, manifest } = await libraryIndex(config)
  const run = runId ? await loadRun(config, runId) : undefined
  const exclude = run && !includeExamined ? new Set(run.examinedChunks) : undefined
  const { terms, hits } = searchIndex(index, query, { limit, exclude })
  const views = hits.map((hit) => hitView(byId.get(hit.chunk.id), hit.score, hit.coverage))
  const documents = Object.values(manifest.documents)
  const result = {
    query,
    terms,
    searchedDocuments: documents.filter((doc) => ['indexed', 'partial'].includes(doc.status)).length,
    pendingDocuments: documents.filter((doc) => ['queued', 'parsing'].includes(doc.status)).length,
    hits: views,
    bestCoverage: views.length ? Math.max(...views.map((hit) => hit.coverage)) : 0,
  }
  result.localSufficient = result.bestCoverage >= LOCAL_MIN_COVERAGE
  if (!views.length)
    result.note = exclude?.size
      ? 'No unexamined passages match. Reformulate, or treat local material as exhausted for this target.'
      : 'No local passages match this query.'
  if (run)
    await updateRun(config, run.runId, (current) => {
      current.searches.push({
        at: now(),
        query,
        hits: views.length,
        bestCoverage: result.bestCoverage,
        localSufficient: result.localSufficient,
      })
      for (const hit of views)
        if (!current.examinedChunks.includes(hit.chunkId)) current.examinedChunks.push(hit.chunkId)
      transition(current, 'local_search', `${query} → ${views.length} hits`)
    })
  return result
}

const acquiredDocIds = (run) =>
  new Set(run.downloads.filter((entry) => entry.ok && entry.docId).map((entry) => entry.docId))

/** Refuse another download once this question already retrieved its paper budget. */
export async function assertCanDownload(config, runId) {
  const run = await loadRun(config, runId)
  const papers = run.downloads.filter((entry) => entry.ok).length
  if (papers >= EXTERNAL_PAPER_LIMIT)
    throw fail(
      'RESEARCH_EXTERNAL_LIMIT',
      `This question already retrieved ${EXTERNAL_PAPER_LIMIT} papers. Finish with outcome=failed.`,
    )
}

export async function readPassage(config, { chunkId, around = 1, runId }) {
  const { byId } = await libraryIndex(config)
  const entry = byId.get(chunkId)
  if (!entry) throw fail('RESEARCH_CHUNK_NOT_FOUND', `Passage ${chunkId} is not in the current library index.`)
  if (runId)
    await updateRun(config, runId, (run) => {
      if (acquiredDocIds(run).has(entry.doc.docId)) return
      const reviews = run.paperReviews?.[entry.doc.docId] ?? 0
      if (reviews >= LOCAL_PAPER_REVIEW_LIMIT)
        throw fail(
          'RESEARCH_PAPER_REVIEW_LIMIT',
          `Paper ${entry.doc.displayName} was already read ${LOCAL_PAPER_REVIEW_LIMIT} times. Finish with outcome=insufficient and say this cannot be answered from that paper.`,
        )
      run.paperReviews = { ...(run.paperReviews ?? {}), [entry.doc.docId]: reviews + 1 }
    })
  const start = Math.max(0, entry.position - around),
    end = Math.min(entry.siblings.length, entry.position + around + 1)
  return {
    document: entry.doc.displayName,
    docId: entry.doc.docId,
    passages: entry.siblings.slice(start, end).map((chunk) => ({
      chunkId: chunk.id,
      ...(chunk.page ? { page: chunk.page } : {}),
      paragraph: chunk.paragraph,
      ...(chunk.section ? { section: chunk.section } : {}),
      target: chunk.id === chunkId,
      text: chunk.text,
    })),
  }
}

/** Locate a quote verbatim (ignoring spacing/punctuation) in its chunk, then anywhere in the document. */
export function locateQuote(entry, quote) {
  const key = matchKey(quote)
  if (key.length < MIN_QUOTE_KEY_LENGTH) return { verification: 'location_failed', reason: 'quote too short' }
  if (matchKey(entry.chunk.text).includes(key)) return { verification: 'verified', chunk: entry.chunk }
  const moved = entry.siblings.find((chunk) => matchKey(chunk.text).includes(key))
  if (moved) return { verification: 'verified', chunk: moved, relocated: true }
  const neighbours = entry.siblings.slice(Math.max(0, entry.position - 1), entry.position + 2)
  if (matchKey(neighbours.map((chunk) => chunk.text).join(' ')).includes(key))
    return { verification: 'verified', chunk: entry.chunk, spansParagraphs: true }
  return { verification: 'location_failed', reason: 'quote not found verbatim in the document' }
}

function contextFor(entry, chunk) {
  const position = entry.siblings.findIndex((sibling) => sibling.id === chunk.id)
  const before = entry.siblings[position - 1]?.text,
    after = entry.siblings[position + 1]?.text
  return [before && `…${before.slice(-CONTEXT_CHARS)}`, after && `${after.slice(0, CONTEXT_CHARS)}…`]
    .filter(Boolean)
    .join('\n---\n')
}

/** Resolve `runId/evidenceId` to evidence of an earlier question in the same conversation. */
async function priorEvidence(config, run, ref) {
  const [runId, evidenceId] = String(ref).split('/')
  const source = runId === run.runId ? undefined : await loadRun(config, runId).catch(() => undefined)
  const record = source?.evidence.find((item) => item.evidenceId === evidenceId)
  if (!record || !run.session || source.session !== run.session)
    throw fail('RESEARCH_REUSE_UNKNOWN', `reusedFrom ${ref} is not evidence of an earlier question in this conversation.`)
  return { runId, evidenceId, question: source.question }
}

/** Store one quote after verifying it. Jev sees the round only through judgeCollectedEvidence. */
export async function addEvidence(config, input) {
  const { byId } = await libraryIndex(config)
  const entry = byId.get(input.chunkId)
  if (!entry) throw fail('RESEARCH_CHUNK_NOT_FOUND', `Passage ${input.chunkId} is not in the library index.`)
  const run = await loadRun(config, input.runId)
  if (run.outcome) throw fail('RESEARCH_RUN_FINISHED', 'This run is finished; start a new one.')
  const claimId = input.claimId ?? run.normalizedClaims[0].id
  if (!run.normalizedClaims.some((claim) => claim.id === claimId))
    throw fail('RESEARCH_CLAIM_UNKNOWN', `Unknown claimId ${claimId}.`)
  const reusedFrom = input.reusedFrom ? await priorEvidence(config, run, input.reusedFrom) : undefined
  const acquired = acquiredDocIds(run)
  if (
    acquired.has(entry.doc.docId) &&
    run.evidence.filter((record) => acquired.has(record.documentId)).length >= EXTERNAL_EVIDENCE_LIMIT
  )
    throw fail(
      'RESEARCH_EXTERNAL_LIMIT',
      `This question already has ${EXTERNAL_EVIDENCE_LIMIT} evidence records from retrieved papers. Finish with outcome=failed.`,
    )
  const located = locateQuote(entry, input.quote)
  const chunk = located.chunk ?? entry.chunk
  const doc = entry.doc
  const record = {
    evidenceId: `e${run.evidence.length + 1}`,
    claimId,
    documentId: doc.docId,
    document: doc.displayName,
    file: doc.relPaths[0],
    documentRevision: doc.contentHash,
    chunkId: chunk.id,
    location: {
      ...(chunk.page ? { page: chunk.page } : {}),
      paragraph: chunk.paragraph,
      ...(chunk.section ? { section: chunk.section } : {}),
    },
    quote: input.quote,
    question: input.question,
    proposedAnswer: input.proposedAnswer,
    acquisition: doc.ocrPages?.includes(chunk.page) ? 'ocr_uncertain' : 'full_text',
    verification: located.verification,
    ...(located.reason ? { verificationNote: located.reason } : {}),
    ...(located.spansParagraphs ? { verificationNote: 'quote spans adjacent paragraphs' } : {}),
    ...(reusedFrom ? { reusedFrom } : {}),
    createdAt: now(),
    passed: false,
  }
  return updateRun(config, run.runId, (current) => {
    record.evidenceId = `e${current.evidence.length + 1}`
    current.evidence.push(record)
    if (!current.examinedChunks.includes(chunk.id)) current.examinedChunks.push(chunk.id)
    transition(current, 'evidence_added', `${record.evidenceId} ${record.verification}`)
    return { record, threshold: config.jev.threshold }
  })
}

/** One Jev call over every verified quote collected for this question. */
export async function judgeCollectedEvidence(config, { runId, proposedAnswer }, { signal, judge = judgeEvidence } = {}) {
  const run = await loadRun(config, runId)
  if (run.outcome) throw fail('RESEARCH_RUN_FINISHED', 'This run is finished; start a new one.')
  const verified = run.evidence.filter((record) => record.verification === 'verified')
  if (!verified.length)
    throw fail('RESEARCH_EVIDENCE_REQUIRED', 'No verified quotes to judge. Add evidence from the papers first.')
  const answer = (proposedAnswer ?? verified.find((record) => record.proposedAnswer)?.proposedAnswer ?? '').trim()
  if (!answer) throw fail('RESEARCH_EVIDENCE_REQUIRED', 'A proposed answer is required when judging the collected evidence.')
  const evidenceIds = verified.map((record) => record.evidenceId)
  let stored
  try {
    const judgement = await judge(
      config.jev,
      {
        question: run.question,
        proposedAnswer: answer,
        evidence: verified.map((record) => ({
          id: record.evidenceId,
          document: record.document,
          ...record.location,
          quote: record.quote,
          proposed_answer: record.proposedAnswer,
        })),
      },
      { signal },
    )
    stored = {
      evidenceIds,
      relation: judgement.relation,
      confidence: judgement.confidence,
      explanation: judgement.explanation,
      judgeVersion: judgement.judgeVersion,
      proposedAnswer: answer,
      passed: passes(judgement, config.jev.threshold),
    }
  } catch (error) {
    if (error?.code === 'RESEARCH_CANCELLED') throw error
    stored = {
      evidenceIds,
      relation: null,
      confidence: null,
      judge: 'judge_unavailable',
      judgeError: describeError(error).message,
      proposedAnswer: answer,
      passed: false,
    }
  }
  return updateRun(config, run.runId, (current) => {
    current.judgement = { at: now(), ...stored }
    transition(current, 'judging_evidence', `${stored.relation ?? stored.judge} ${stored.evidenceIds.length}`)
    return { judgement: current.judgement, threshold: config.jev.threshold }
  })
}

export function logStage(config, { runId, stage, detail }) {
  return updateRun(config, runId, (run) => {
    run.logs.push({ at: now(), stage, detail: clip(detail, 4000) })
    if (stage !== 'note') transition(run, stage, detail)
    return { runId, state: run.state }
  })
}

export function recordDownload(config, runId, entry) {
  return updateRun(config, runId, (run) => {
    run.downloads.push({ at: now(), ...entry })
    transition(run, entry.ok ? 'importing' : 'acquisition_unavailable', entry.ok ? entry.relPath : entry.error)
  })
}

function evidenceView(record) {
  return {
    id: record.evidenceId,
    claim: record.claimId,
    document: record.document,
    file: record.file,
    ...record.location,
    quote: record.quote,
    proposedAnswer: record.proposedAnswer,
    relation: record.relation ?? null,
    confidence: record.confidence ?? null,
    passed: record.passed,
    verification: record.verification,
    acquisition: record.acquisition,
    ...(record.judge ? { judge: record.judge } : {}),
    ...(record.judgeExplanation ? { judgeExplanation: record.judgeExplanation } : {}),
    ...(record.reusedFrom ? { reusedFrom: record.reusedFrom } : {}),
  }
}

export function runSummary(run, threshold) {
  const claims = run.normalizedClaims.map((claim) => {
    const items = run.evidence.filter((record) => record.claimId === claim.id)
    const passed = items.filter((record) => record.passed)
    const relations = new Set(passed.map((record) => record.relation))
    return {
      ...claim,
      evidence: items.length,
      passed: passed.length,
      conflicting: relations.has('supports') && relations.has('contradicts'),
    }
  })
  return {
    runId: run.runId,
    question: run.question,
    state: run.state,
    ...(run.outcome ? { outcome: run.outcome } : {}),
    threshold,
    claims,
    searches: run.searches.length,
    examinedPassages: run.examinedChunks.length,
    downloads: run.downloads,
    ...(run.judgement
      ? {
          judgement: {
            relation: run.judgement.relation ?? null,
            confidence: run.judgement.confidence ?? null,
            passed: run.judgement.passed === true,
            evidenceIds: run.judgement.evidenceIds ?? [],
            ...(run.judgement.explanation ? { explanation: run.judgement.explanation } : {}),
            ...(run.judgement.judge ? { judge: run.judgement.judge, judgeError: run.judgement.judgeError } : {}),
          },
        }
      : {}),
    evidence: run.evidence.map(evidenceView),
  }
}

/** An answer must rest on one Jev judgement of every verified quote together. */
function judgementCovers(run) {
  const ids = run.evidence
    .filter((record) => record.verification === 'verified')
    .map((record) => record.evidenceId)
    .sort()
  const judged = [...(run.judgement?.evidenceIds ?? [])].sort()
  return ids.length > 0 && ids.join('|') === judged.join('|')
}

function requireGrounding(run, outcome) {
  const judgement = run.judgement
  const covered = judgementCovers(run)
  if (outcome === 'answered' && !(covered && judgement?.passed && judgement.relation !== 'conditional'))
    throw fail(
      'RESEARCH_EVIDENCE_REQUIRED',
      'outcome=answered needs one passing Jev judgement of every verified quote together. Call research_judge, or finish with outcome=insufficient.',
    )
  if (outcome === 'conflict' && !(covered && judgement?.passed && judgement.relation === 'conditional'))
    throw fail(
      'RESEARCH_EVIDENCE_REQUIRED',
      'outcome=conflict needs a passing pooled Jev judgement whose relation is conditional.',
    )
}

export function finishRun(config, { runId, outcome, summary }) {
  return updateRun(config, runId, (run) => {
    if (run.outcome) return runSummary(run, config.jev.threshold)
    requireGrounding(run, outcome)
    transition(run, 'citation_check')
    run.outcome = outcome
    if (summary) run.summary = clip(summary, 4000)
    transition(run, ['failed', 'cancelled'].includes(outcome) ? outcome : 'completed', outcome)
    return runSummary(run, config.jev.threshold)
  })
}
