import { describe, expect, it } from 'vitest'
import { deriveResearchFlow, isFlowCall, type ResearchCall } from '../src/research-flow.js'
import { modeCatalog, modeOfPreset, presetForMode } from '../src/research-mode.js'

let seq = 0
const done = (name: string, args: Record<string, unknown>, result: unknown): ResearchCall => ({
  seq: ++seq,
  name,
  status: 'completed',
  args,
  result,
})
const stateOf = (calls: ResearchCall[]) =>
  Object.fromEntries(deriveResearchFlow(calls).stages.map((stage) => [stage.id, stage.state]))

const START = done(
  'research_start',
  { question: 'Does X improve Y?' },
  {
    runId: 'r1',
    claims: [{ id: 'C1', text: 'X improves Y' }],
    threshold: 0.7,
    library: '/papers',
    judgeModel: 'jev',
  },
)

describe('deriveResearchFlow', () => {
  it('walks a local run from question to answer and pools the judged evidence', () => {
    const flow = deriveResearchFlow([
      START,
      done('research_library_import', {}, { documents: 3, indexed: 3, pending: 0, failed: 0 }),
      done(
        'research_search',
        { query: 'x y' },
        { hits: [{ document: 'a.pdf', page: 2 }], bestCoverage: 0.8, localSufficient: true },
      ),
      done(
        'research_add_evidence',
        { claimId: 'C1', quote: 'X raised Y.', proposedAnswer: 'yes' },
        {
          evidenceId: 'E1',
          verification: 'verified',
          relation: 'supports',
          confidence: 0.9,
          passed: true,
          location: { document: 'a.pdf', page: 2 },
        },
      ),
      done('research_finish', { outcome: 'answered', summary: 'Supported.' }, {}),
    ])
    expect(flow).toMatchObject({
      runId: 'r1',
      question: 'Does X improve Y?',
      threshold: 0.7,
      outcome: 'answered',
    })
    expect(Object.fromEntries(flow.stages.map((stage) => [stage.id, stage.state]))).toEqual({
      question: 'done',
      library: 'done',
      local: 'done',
      external: 'skipped',
      acquire: 'skipped',
      reading: 'skipped',
      pool: 'done',
      judge: 'done',
      answer: 'done',
    })
    expect(flow.evidence).toEqual([
      expect.objectContaining({ id: 'E1', claim: 'C1', page: 2, relation: 'supports', passed: true }),
    ])
  })

  it('counts Athenaeum calls as the external stage, by tool name or deferred-invoke argument', () => {
    const external = [
      done('mcp_athenaeum_1a2b3c4d_athenaeum_search', { query: 'x' }, {}),
      done('tool_invoke', { name: 'mcp_athenaeum_1a2b3c4d_athenaeum_find_pdf' }, {}),
    ]
    expect(external.every(isFlowCall)).toBe(true)
    expect(isFlowCall({ name: 'shell', args: { command: 'ls' } })).toBe(false)
    const stage = deriveResearchFlow([START, ...external]).stages.find(({ id }) => id === 'external')
    expect(stage).toMatchObject({ state: 'done', counts: { calls: 2 } })
    expect(stage?.items.map(({ label }) => label)).toEqual(['athenaeum_search', 'tool_invoke'])
  })

  it('reports a missing configuration and fails the stage that refused', () => {
    const flow = deriveResearchFlow([
      {
        seq: ++seq,
        name: 'research_start',
        status: 'failed',
        args: { question: 'q' },
        error: 'Research tool failed (RESEARCH_CONFIG_MISSING): create ~/agnes-research.config.json',
      },
    ])
    expect(flow.config).toEqual({
      code: 'RESEARCH_CONFIG_MISSING',
      message: 'create ~/agnes-research.config.json',
    })
    expect(flow.stages.find(({ id }) => id === 'question')?.state).toBe('failed')
  })

  it('starts the flow afresh for a new question and keeps earlier questions as history', () => {
    const evidence = done(
      'research_add_evidence',
      { claimId: 'C1', quote: 'X raised Y.' },
      { evidenceId: 'E1', verification: 'verified', passed: true, location: { document: 'a.pdf' } },
    )
    const earlier = done('research_finish', { outcome: 'insufficient' }, {})
    const again = done('research_start', { question: 'second' }, { runId: 'r2', claims: [] })
    const reused = done(
      'research_add_evidence',
      { claimId: 'c1', quote: 'X raised Y.' },
      {
        evidenceId: 'e1',
        verification: 'verified',
        passed: false,
        location: { document: 'a.pdf' },
        reusedFrom: { runId: 'r1', evidenceId: 'E1', question: 'Does X improve Y?' },
      },
    )
    const running: ResearchCall = {
      seq: ++seq,
      name: 'research_search',
      status: 'running',
      args: { query: 'q' },
    }
    const calls = [START, evidence, earlier, again, reused, running]
    const flow = deriveResearchFlow(calls)
    expect(flow).toMatchObject({ runId: 'r2', question: 'second' })
    expect(flow.outcome).toBeUndefined()
    expect(stateOf(calls)).toMatchObject({ question: 'done', local: 'active', answer: 'idle' })
    expect(flow.evidence).toEqual([
      expect.objectContaining({
        id: 'e1',
        reusedFrom: { runId: 'r1', evidenceId: 'E1', question: 'Does X improve Y?' },
      }),
    ])
    expect(flow.history).toEqual([
      expect.objectContaining({
        runId: 'r1',
        question: 'Does X improve Y?',
        outcome: 'insufficient',
        documents: ['a.pdf'],
        evidence: [expect.objectContaining({ id: 'E1', passed: true })],
      }),
    ])
  })

  it('judges one round of verified quotes together', () => {
    const quotes = [
      done(
        'research_add_evidence',
        { quote: 'X raised Y.' },
        { evidenceId: 'E1', verification: 'verified', relation: null, passed: false },
      ),
      done(
        'research_add_evidence',
        { quote: 'Y stayed higher.' },
        { evidenceId: 'E2', verification: 'verified', relation: null, passed: false },
      ),
    ]
    expect(deriveResearchFlow([START, ...quotes]).evidence.map((item) => item.round)).toEqual([
      'pending',
      'pending',
    ])
    const flow = deriveResearchFlow([
      START,
      ...quotes,
      done(
        'research_judge',
        { proposedAnswer: 'yes' },
        { relation: 'supports', confidence: 0.95, passed: true, evidenceCount: 2, evidenceIds: ['E1', 'E2'] },
      ),
    ])
    expect(flow.stages.find(({ id }) => id === 'judge')).toMatchObject({
      state: 'done',
      counts: { pooled: 1, judged: 2, passed: 2, unavailable: 0, confidence: 0.95 },
      items: [{ label: 'supports 0.95' }],
    })
    expect(flow.evidence.map((item) => item.round)).toEqual(['included', 'included'])
  })

  it('warns when the judge was unavailable or the quote could not be located', () => {
    const states = stateOf([
      START,
      done(
        'research_add_evidence',
        { claimId: 'C1', quote: 'q' },
        {
          evidenceId: 'E1',
          verification: 'location_failed',
          relation: null,
          confidence: null,
          passed: false,
        },
      ),
      done(
        'research_add_evidence',
        { claimId: 'C1', quote: 'q' },
        { evidenceId: 'E2', verification: 'verified', judge: 'judge_unavailable', passed: false },
      ),
    ])
    expect(states).toMatchObject({ pool: 'warn', judge: 'warn' })
  })
})

describe('workbench modes', () => {
  it.each([
    [
      { default: 'standard', allowed: ['standard', 'research'] },
      { harness: 'standard', research: 'research' },
    ],
    [
      { default: 'standard-windows', allowed: ['standard-windows', 'research-windows'] },
      { harness: 'standard-windows', research: 'research-windows' },
    ],
    [{ default: 'standard', allowed: ['standard'] }, { harness: 'standard' }],
  ])('maps the profile presets %j to %j', (presets, catalog) => {
    expect(modeCatalog(presets)).toEqual(catalog)
  })

  it('treats any preset other than the research recipe as Harness', () => {
    const catalog = modeCatalog({ default: 'standard', allowed: ['standard', 'research', 'code'] })
    expect(modeOfPreset(catalog, 'research')).toBe('research')
    expect(modeOfPreset(catalog, 'code')).toBe('harness')
    expect(modeOfPreset(catalog, undefined)).toBe('harness')
    expect(presetForMode(catalog, 'research')).toBe('research')
    expect(presetForMode(modeCatalog({ default: 'standard', allowed: ['standard'] }), 'research')).toBe(
      'standard',
    )
  })
})
