/**
 * The research workflow as the panel shows it, derived only from the session's own tool calls.
 *
 * Each `research_*` tool answers with one JSON text block and fails with
 * `Research tool failed (CODE): message`; Athenaeum is an MCP server whose local tool names (or the
 * deferred-invoke arguments) carry `athenaeum`. Nothing here reads the plugin's files or config.
 */

export type ResearchCallStatus = 'planned' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ResearchCall {
  readonly seq: number
  readonly name: string
  readonly status: ResearchCallStatus
  readonly args?: Readonly<Record<string, unknown>>
  /** The parsed JSON result of a completed research tool; arbitrary for other tools. */
  readonly result?: unknown
  /** The text of an error result. */
  readonly error?: string
}

export const RESEARCH_STAGES = [
  'question',
  'library',
  'local',
  'external',
  'acquire',
  'reading',
  'pool',
  'judge',
  'answer',
] as const
export type ResearchStageId = (typeof RESEARCH_STAGES)[number]
export type ResearchStageState = 'idle' | 'active' | 'done' | 'warn' | 'failed' | 'skipped'
export type ResearchTone = 'ok' | 'warn' | 'bad'

export interface ResearchStageItem {
  readonly label: string
  readonly detail?: string
  readonly tone?: ResearchTone
}

export interface ResearchStage {
  readonly id: ResearchStageId
  readonly state: ResearchStageState
  /** Numbers the panel renders through its own locale strings, keyed by stage. */
  readonly counts: Readonly<Record<string, number>>
  readonly items: readonly ResearchStageItem[]
}

export interface ResearchEvidence {
  readonly id: string
  readonly claim?: string
  readonly document?: string
  readonly page?: number
  readonly paragraph?: number
  readonly quote?: string
  readonly answer?: string
  readonly verification?: string
  readonly relation: string | null
  readonly confidence: number | null
  readonly passed: boolean
  readonly judgeUnavailable: boolean
  /** Verified quotes wait for one pooled judgement, then belong to that round. */
  readonly round?: 'pending' | 'included'
  readonly explanation?: string
  /** Set when the quote was carried over from an earlier question and judged again for this one. */
  readonly reusedFrom?: { readonly runId: string; readonly evidenceId: string; readonly question?: string }
}

/** An earlier question of this conversation; its papers and evidence stay available for reuse. */
export interface ResearchHistoryEntry {
  readonly runId?: string
  readonly question?: string
  readonly outcome?: string
  readonly documents: readonly string[]
  readonly evidence: readonly ResearchEvidence[]
}

export interface ResearchFlow {
  readonly runId?: string
  readonly question?: string
  readonly claims: ReadonlyArray<{ id: string; text: string }>
  readonly threshold?: number
  readonly library?: string
  readonly judgeModel?: string
  readonly outcome?: string
  /** Set when a research tool refused to run because its configuration file is missing or invalid. */
  readonly config?: { readonly code: string; readonly message: string }
  readonly stages: readonly ResearchStage[]
  readonly evidence: readonly ResearchEvidence[]
  /** Earlier questions, oldest first; the stages and evidence above belong to the latest question only. */
  readonly history: readonly ResearchHistoryEntry[]
}

const FAILURE = /^Research tool failed \(([A-Z0-9_]+)\): ([\s\S]*)$/
const WARN_OUTCOMES = new Set(['insufficient', 'conflict', 'acquisition_unavailable'])
const BAD_OUTCOMES = new Set(['failed', 'cancelled'])
const EXTERNAL_LOGS = new Set([
  'mcp_search',
  'candidate_selected',
  'fulltext_check',
  'external_search_unavailable',
])

type Json = Record<string, unknown>
const record = (value: unknown): Json =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {}
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])
const str = (value: unknown): string | undefined => (typeof value === 'string' ? value : undefined)
const num = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined

export function isResearchTool(name: string): boolean {
  return name.startsWith('research_')
}

export function isExternalSearch(call: Pick<ResearchCall, 'name' | 'args'>): boolean {
  if (isResearchTool(call.name)) return false
  if (/athenaeum/i.test(call.name)) return true
  return Object.values(call.args ?? {}).some((value) => typeof value === 'string' && /athenaeum/i.test(value))
}

/** Calls the panel reads; everything else in the conversation stays out of the flow. */
export function isFlowCall(call: Pick<ResearchCall, 'name' | 'args'>): boolean {
  return isResearchTool(call.name) || isExternalSearch(call)
}

export function parseFailure(text: string | undefined): { code: string; message: string } | undefined {
  const match = text ? FAILURE.exec(text.trim()) : null
  return match ? { code: match[1] as string, message: (match[2] as string).trim() } : undefined
}

class StageBuilder {
  state: ResearchStageState = 'idle'
  readonly counts: Record<string, number> = {}
  readonly items: ResearchStageItem[] = []
  constructor(readonly id: ResearchStageId) {}
  add(key: string, by = 1): void {
    this.counts[key] = (this.counts[key] ?? 0) + by
  }
  max(key: string, value: number): void {
    this.counts[key] = Math.max(this.counts[key] ?? 0, value)
  }
  /** Later evidence only raises the severity; an active call shows until it settles. */
  mark(state: ResearchStageState): void {
    const rank: Record<ResearchStageState, number> = {
      idle: 0,
      skipped: 0,
      done: 1,
      warn: 2,
      failed: 3,
      active: 4,
    }
    if (rank[state] >= rank[this.state]) this.state = state
  }
  push(item: ResearchStageItem, limit = 12): void {
    this.items.push(item)
    if (this.items.length > limit) this.items.shift()
  }
  view(): ResearchStage {
    return { id: this.id, state: this.state, counts: { ...this.counts }, items: [...this.items] }
  }
}

function stageOf(call: ResearchCall): ResearchStageId | undefined {
  if (isExternalSearch(call)) return 'external'
  switch (call.name) {
    case 'research_start':
      return 'question'
    case 'research_library_import':
    case 'research_library_list':
      return 'library'
    case 'research_search':
      return 'local'
    case 'research_download':
      return 'acquire'
    case 'research_read':
      return 'reading'
    case 'research_add_evidence':
    case 'research_history':
      return 'pool'
    case 'research_judge':
      return 'judge'
    case 'research_finish':
      return 'answer'
    case 'research_log': {
      const stage = str(call.args?.stage)
      if (stage === 'acquisition_unavailable') return 'acquire'
      return stage && EXTERNAL_LOGS.has(stage) ? 'external' : undefined
    }
    default:
      return undefined
  }
}

function evidenceOf(result: Json, args: Readonly<Record<string, unknown>>): ResearchEvidence {
  const location = record(result.location)
  return {
    id: str(result.evidenceId) ?? '?',
    ...(str(args.claimId) ? { claim: str(args.claimId) as string } : {}),
    ...(str(location.document) ? { document: str(location.document) as string } : {}),
    ...(num(location.page) !== undefined ? { page: num(location.page) as number } : {}),
    ...(num(location.paragraph) !== undefined ? { paragraph: num(location.paragraph) as number } : {}),
    ...(str(args.quote) ? { quote: str(args.quote) as string } : {}),
    ...(str(args.proposedAnswer) ? { answer: str(args.proposedAnswer) as string } : {}),
    ...(str(result.verification) ? { verification: str(result.verification) as string } : {}),
    relation: str(result.relation) ?? null,
    confidence: num(result.confidence) ?? null,
    passed: result.passed === true,
    judgeUnavailable: result.judge === 'judge_unavailable',
    ...(str(result.judgeExplanation) ? { explanation: str(result.judgeExplanation) as string } : {}),
    ...reuseOf(result.reusedFrom),
  }
}

function reuseOf(value: unknown): Pick<ResearchEvidence, 'reusedFrom'> {
  const source = record(value)
  const runId = str(source.runId)
  const evidenceId = str(source.evidenceId)
  if (!runId || !evidenceId) return {}
  const question = str(source.question)
  return { reusedFrom: { runId, evidenceId, ...(question ? { question } : {}) } }
}

/** One segment per `research_start`; calls before the first one belong to the first segment. */
function questionSegments(calls: readonly ResearchCall[]): ResearchCall[][] {
  const segments: ResearchCall[][] = [[]]
  for (const call of [...calls].sort((a, b) => a.seq - b.seq)) {
    const last = segments[segments.length - 1] as ResearchCall[]
    if (call.name === 'research_start' && last.some((c) => c.name === 'research_start')) segments.push([call])
    else last.push(call)
  }
  return segments
}

function historyEntry(flow: Omit<ResearchFlow, 'history'>): ResearchHistoryEntry {
  return {
    ...(flow.runId ? { runId: flow.runId } : {}),
    ...(flow.question ? { question: flow.question } : {}),
    ...(flow.outcome ? { outcome: flow.outcome } : {}),
    documents: [...new Set(flow.evidence.flatMap((item) => (item.document ? [item.document] : [])))],
    evidence: flow.evidence,
  }
}

/** The latest question's stages and evidence start fresh; earlier questions become history. */
export function deriveResearchFlow(calls: readonly ResearchCall[]): ResearchFlow {
  const segments = questionSegments(calls)
  const current = deriveQuestionFlow(segments[segments.length - 1] as ResearchCall[])
  const history = segments.slice(0, -1).map((segment) => historyEntry(deriveQuestionFlow(segment)))
  return { ...current, history }
}

function deriveQuestionFlow(calls: readonly ResearchCall[]): Omit<ResearchFlow, 'history'> {
  const stages = new Map(RESEARCH_STAGES.map((id) => [id, new StageBuilder(id)]))
  const stage = (id: ResearchStageId) => stages.get(id) as StageBuilder
  const evidence: ResearchEvidence[] = []
  let pooledRound: { ids: Set<string>; held: boolean } | undefined
  let flow: {
    runId?: string
    question?: string
    claims: Array<{ id: string; text: string }>
    threshold?: number
    library?: string
    judgeModel?: string
    outcome?: string
    config?: { code: string; message: string }
  } = { claims: [] }

  for (const call of calls) {
    const id = stageOf(call)
    if (!id) continue
    const target = stage(id)
    const args = call.args ?? {}
    if (call.status === 'planned' || call.status === 'running') {
      target.mark('active')
      if (call.name === 'research_start' && str(args.question)) flow.question = str(args.question) as string
      continue
    }
    if (call.status === 'cancelled') continue
    if (call.status === 'failed') {
      const failure = parseFailure(call.error)
      if (failure?.code.startsWith('RESEARCH_CONFIG')) flow.config = failure
      target.mark(id === 'external' || id === 'acquire' ? 'warn' : 'failed')
      target.push({
        label: failure?.code ?? call.name,
        detail: failure?.message ?? call.error ?? '',
        tone: 'bad',
      })
      continue
    }
    const result = record(call.result)
    switch (call.name) {
      case 'research_start': {
        flow = {
          ...flow,
          ...(str(result.runId) ? { runId: str(result.runId) as string } : {}),
          ...(str(args.question) ? { question: str(args.question) as string } : {}),
          claims: list(result.claims).map((claim) => ({
            id: str(record(claim).id) ?? '',
            text: str(record(claim).text) ?? '',
          })),
          ...(num(result.threshold) !== undefined ? { threshold: num(result.threshold) as number } : {}),
          ...(str(result.library) ? { library: str(result.library) as string } : {}),
          ...(str(result.judgeModel) ? { judgeModel: str(result.judgeModel) as string } : {}),
        }
        delete flow.config
        target.mark('done')
        target.counts.claims = flow.claims.length
        break
      }
      case 'research_library_import': {
        for (const key of ['documents', 'indexed', 'partial', 'failed', 'pending'] as const)
          if (num(result[key]) !== undefined) target.counts[key] = num(result[key]) as number
        target.mark((num(result.pending) ?? 0) > 0 || (num(result.failed) ?? 0) > 0 ? 'warn' : 'done')
        for (const problem of list(result.problems).slice(0, 6))
          target.push({
            label: str(record(problem).file) ?? '?',
            detail: str(record(problem).reason) ?? str(record(problem).status) ?? '',
            tone: 'warn',
          })
        break
      }
      case 'research_library_list':
        target.mark('done')
        target.max('documents', list(result.documents).length)
        break
      case 'research_search': {
        const hits = list(result.hits)
        target.add('searches')
        target.add('hits', hits.length)
        target.max('coverage', Math.round((num(result.bestCoverage) ?? 0) * 100))
        if (result.localSufficient === true) target.counts.sufficient = 1
        target.mark(hits.length ? 'done' : 'warn')
        const tone = result.localSufficient === true ? 'ok' : hits.length ? undefined : 'warn'
        target.push({
          label: str(result.query) ?? str(args.query) ?? '',
          detail: hits
            .slice(0, 3)
            .map((hit) => {
              const h = record(hit)
              const page = num(h.page)
              return `${str(h.document) ?? '?'}${page !== undefined ? ` p.${page}` : ''}`
            })
            .join(' · '),
          ...(tone ? { tone } : {}),
        })
        break
      }
      case 'research_read':
        target.add('passages', list(result.passages).length)
        target.mark('done')
        target.push({ label: str(result.document) ?? str(args.chunkId) ?? '' })
        break
      case 'research_download':
        target.add('downloaded')
        target.mark('done')
        target.push({ label: str(result.file) ?? str(args.title) ?? str(args.url) ?? '', tone: 'ok' })
        break
      case 'research_log': {
        const logStage = str(args.stage) ?? ''
        const unavailable =
          logStage === 'external_search_unavailable' || logStage === 'acquisition_unavailable'
        if (logStage === 'candidate_selected') target.add('candidates')
        target.mark(unavailable ? 'warn' : 'done')
        target.push({
          label: logStage,
          detail: str(args.detail) ?? '',
          ...(unavailable ? { tone: 'warn' } : {}),
        })
        break
      }
      case 'research_add_evidence': {
        const item = evidenceOf(result, args)
        evidence.push(item)
        target.mark('done')
        break
      }
      case 'research_judge': {
        const ids = list(result.evidenceIds).flatMap((item) => {
          const id = str(item)
          return id ? [id] : []
        })
        const count = num(result.evidenceCount) ?? ids.length
        target.counts.pooled = 1
        target.counts.judged = count
        target.counts.passed = result.passed === true ? count : 0
        target.counts.unavailable = result.judge === 'judge_unavailable' ? 1 : 0
        pooledRound = { ids: new Set(ids), held: result.judge !== 'judge_unavailable' }
        target.mark(result.judge === 'judge_unavailable' || result.passed !== true ? 'warn' : 'done')
        const confidence = num(result.confidence)
        if (confidence !== undefined) target.counts.confidence = confidence
        else delete target.counts.confidence
        const relation = str(result.relation) ?? str(result.judge) ?? 'judge'
        target.push({
          label: confidence !== undefined ? `${relation} ${confidence.toFixed(2)}` : relation,
          ...(str(result.explanation) ? { detail: str(result.explanation) as string } : {}),
        })
        break
      }
      case 'research_history': {
        const runs = list(result.runs)
        target.max('earlier', runs.length)
        target.mark('done')
        for (const run of runs.slice(-6))
          target.push({ label: str(record(run).question) ?? str(record(run).runId) ?? '' })
        break
      }
      case 'research_finish': {
        const outcome = str(args.outcome)
        if (outcome) flow.outcome = outcome
        target.mark(
          outcome && BAD_OUTCOMES.has(outcome)
            ? 'failed'
            : outcome && WARN_OUTCOMES.has(outcome)
              ? 'warn'
              : 'done',
        )
        if (str(args.summary)) target.push({ label: str(args.summary) as string })
        break
      }
      default:
        target.add('calls')
        target.mark('done')
        target.push({ label: call.name.replace(/^mcp_.*?_[0-9a-f]{8}_/, '') })
    }
  }

  const pool = stage('pool')
  pool.counts.total = evidence.length
  pool.counts.verified = evidence.filter((item) => item.verification === 'verified').length
  if (evidence.some((item) => item.verification && item.verification !== 'verified')) pool.mark('warn')
  const judge = stage('judge')
  if (!judge.counts.pooled) {
    const judged = evidence.filter((item) => item.relation !== null)
    judge.counts.judged = judged.length
    judge.counts.passed = evidence.filter((item) => item.passed).length
    judge.counts.unavailable = evidence.filter((item) => item.judgeUnavailable).length
    if (pool.state === 'active') judge.mark('active')
    if (judged.length) judge.mark('done')
    if (judge.counts.unavailable) judge.mark('warn')
  }
  for (let index = 0; index < evidence.length; index++) {
    const item = evidence[index] as ResearchEvidence
    if (item.relation !== null || item.judgeUnavailable || item.verification !== 'verified') continue
    const included = pooledRound?.held === true && pooledRound.ids.has(item.id)
    evidence[index] = { ...item, round: included ? 'included' : 'pending' }
  }

  if (flow.outcome)
    for (const builder of stages.values()) if (builder.state === 'idle') builder.state = 'skipped'

  return {
    ...flow,
    stages: RESEARCH_STAGES.map((id) => stage(id).view()),
    evidence,
  }
}

/** Parse a research tool's JSON text; any other text is kept out of the flow. */
export function parseResearchResult(text: string | undefined): unknown {
  if (!text) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}
