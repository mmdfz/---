import { loadConfig } from './src/config.mjs'
import { fetchPdf, saveDownload } from './src/download.mjs'
import { describeError } from './src/errors.mjs'
import { documentView, importLibrary, librarySummary, scanLibrary } from './src/library.mjs'
import {
  addEvidence,
  finishRun,
  judgeCollectedEvidence,
  getRun,
  LOG_STAGES,
  logStage,
  OUTCOMES,
  readPassage,
  recordDownload,
  assertCanDownload,
  runHistory,
  runSummary,
  searchLibrary,
  startRun,
} from './src/research.mjs'
import { array, boolean, enumeration, integer, object, optional, string } from './src/schema.mjs'
import { loadManifest, statePaths } from './src/store.mjs'

const DEADLINE_MARGIN_MS = 15_000
const runId = () => string({ minLength: 10, maxLength: 80 })

const meta = ({ readOnly = false, openWorld = false, replay = 'never' } = {}) => ({
  isReadOnly: readOnly,
  isDestructive: false,
  isConcurrencySafe: readOnly,
  isOpenWorld: openWorld,
  replay,
  costHint: {},
  deferLoading: false,
  requiresApproval: 'never',
})

const text = (value) => ({ content: [{ type: 'text', text: JSON.stringify(value) }] })

const failure = (error) => {
  const { code, message } = describeError(error)
  return { isError: true, content: [{ type: 'text', text: `Research tool failed (${code}): ${message}` }] }
}

const deadlineOf = (context) =>
  Date.now() + Math.max(10_000, (context.timeoutMs ?? 120_000) - DEADLINE_MARGIN_MS)

async function importStep(config, context) {
  const { manifest, scan, processed } = await importLibrary(config, {
    deadline: deadlineOf(context),
    signal: context.signal,
    progress: (note) => context.progress?.(note),
  })
  const summary = librarySummary(manifest, scan)
  return {
    library: config.libraryDir,
    ...summary,
    processedNow: processed.map((docId) => documentView(manifest.documents[docId])).filter(Boolean),
    problems: Object.values(manifest.files)
      .filter((file) => ['unsupported', 'failed'].includes(file.status))
      .slice(0, 30)
      .map((file) => ({ file: file.relPath, status: file.status, reason: file.error }))
      .concat(
        Object.values(manifest.documents)
          .filter((doc) => doc.status === 'failed')
          .slice(0, 30)
          .map((doc) => ({ file: doc.relPaths[0], status: 'failed', reason: doc.error })),
      ),
    next: summary.pending
      ? `${summary.pending} document(s) still indexing; call research_library_import again.`
      : 'Library index is up to date.',
  }
}

const tools = [
  {
    name: 'research_start',
    description:
      'Start (or resume) a research run for one question. Pass the question and 1-5 English claims/sub-questions to verify. Returns runId and claim ids used by the other research_* tools.',
    parameters: object({
      question: string({ minLength: 3, maxLength: 4000 }),
      claims: optional(array(string({ minLength: 3, maxLength: 1000 }), { maxItems: 5 })),
    }),
    meta: meta({ replay: 'idempotent' }),
    async run(config, args, context) {
      const { run, resumed, history } = await startRun(config, args, { session: context.session?.key })
      return {
        runId: run.runId,
        resumed,
        state: run.state,
        claims: run.normalizedClaims,
        threshold: config.jev.threshold,
        library: config.libraryDir,
        judgeModel: config.jev.model,
        earlierQuestions: history,
        ...(history.length
          ? {
              next: 'Earlier questions in this conversation have papers and evidence; call research_history to reuse what is relevant.',
            }
          : {}),
      }
    },
  },
  {
    name: 'research_history',
    description:
      'Papers and verified quotes from earlier questions in this conversation (ref, chunkId, document, page, quote, earlier question, relation, passed). Reuse a relevant quote by calling research_add_evidence with its chunkId, the same quote, the current question and reusedFrom=ref; it is verified and judged again for the current question.',
    parameters: object({ runId: runId() }),
    meta: meta({ readOnly: true, replay: 'safe' }),
    run: (config, args) => runHistory(config, args),
  },
  {
    name: 'research_library_import',
    description:
      "Scan the paper library folder (the framework's paper folder unless libraryDir is configured) and index new or changed PDF/DOCX/DOC/TXT/MD files (offline, English OCR for scanned pages). Long folders are indexed across several calls; repeat while it reports pending documents.",
    parameters: object({}),
    meta: meta({ replay: 'idempotent' }),
    run: (config, _args, context) => importStep(config, context),
  },
  {
    name: 'research_library_list',
    description: 'List documents in the paper library index with their status, page count, warnings and errors.',
    parameters: object({
      status: optional(enumeration('indexed', 'partial', 'failed', 'queued', 'parsing', 'unsupported')),
    }),
    meta: meta({ readOnly: true, replay: 'safe' }),
    async run(config, args) {
      const manifest = await loadManifest(statePaths(config))
      if (args.status === 'unsupported')
        return Object.values(manifest.files)
          .filter((file) => file.status === 'unsupported')
          .map((file) => ({ file: file.relPath, reason: file.error }))
      const { files } = await scanLibrary(config)
      const known = new Set(Object.keys(manifest.files))
      return {
        documents: Object.values(manifest.documents)
          .filter((doc) => !args.status || doc.status === args.status)
          .slice(0, 200)
          .map(documentView),
        notYetImported: files.filter((file) => !known.has(file.relPath)).length,
      }
    },
  },
  {
    name: 'research_search',
    description:
      'BM25 keyword search (English) over indexed library passages. Returns passages with chunkId, document, page, paragraph, section and coverage (share of query terms matched), plus localSufficient. With runId, passages already returned in this run are skipped so exhaustion becomes visible.',
    parameters: object({
      query: string({ minLength: 2, maxLength: 500 }),
      runId: optional(runId()),
      limit: optional(integer(1, 20)),
      includeExamined: optional(boolean()),
    }),
    meta: meta({ replay: 'safe' }),
    run: (config, args) => searchLibrary(config, args),
  },
  {
    name: 'research_read',
    description:
      'Read a library passage by chunkId together with its neighbouring paragraphs (around = 0-3). Pass runId. A paper already in the library may be read at most 3 times in one question; the next read is refused.',
    parameters: object({
      runId: runId(),
      chunkId: string({ minLength: 5, maxLength: 120 }),
      around: optional(integer(0, 3)),
    }),
    meta: meta({ readOnly: true, replay: 'safe' }),
    run: (config, args) => readPassage(config, args),
  },
  {
    name: 'research_add_evidence',
    description:
      'Verify one verbatim quote and store it in the evidence pool. This does not call Jev. After the round of quotes is stored, call research_judge once so Jev assesses them together. At most 10 evidence records may come from papers downloaded for this question.',
    parameters: object({
      runId: runId(),
      chunkId: string({ minLength: 5, maxLength: 120 }),
      claimId: optional(string({ minLength: 2, maxLength: 8 })),
      quote: string({ minLength: 10, maxLength: 2000 }),
      question: string({ minLength: 3, maxLength: 1000 }),
      proposedAnswer: string({ minLength: 2, maxLength: 2000 }),
      reusedFrom: optional(string({ minLength: 5, maxLength: 120 })),
    }),
    meta: meta({ openWorld: true }),
    async run(config, args, context) {
      const { record, threshold } = await addEvidence(config, args)
      return {
        evidenceId: record.evidenceId,
        verification: record.verification,
        ...(record.verificationNote ? { verificationNote: record.verificationNote } : {}),
        location: { document: record.document, ...record.location },
        relation: record.relation ?? null,
        confidence: record.confidence ?? null,
        passed: record.passed,
        threshold,
        ...(record.judgeExplanation ? { judgeExplanation: record.judgeExplanation } : {}),
        ...(record.judge ? { judge: record.judge, judgeError: record.judgeError } : {}),
        ...(record.reusedFrom ? { reusedFrom: record.reusedFrom } : {}),
      }
    },
  },
  {
    name: 'research_judge',
    description:
      'Send every verified quote of this question to Jev in one request. Jev judges the set together and returns one relation, confidence and passed. Call it again after adding more quotes; a new verified quote makes the previous judgement stale. Unverified quotes are not sent.',
    parameters: object({
      runId: runId(),
      proposedAnswer: string({ minLength: 2, maxLength: 2000 }),
    }),
    meta: meta({ openWorld: true }),
    async run(config, args, context) {
      const { judgement, threshold } = await judgeCollectedEvidence(config, args, { signal: context.signal })
      return {
        relation: judgement.relation ?? null,
        confidence: judgement.confidence ?? null,
        passed: judgement.passed === true,
        evidenceCount: judgement.evidenceIds.length,
        evidenceIds: judgement.evidenceIds,
        threshold,
        ...(judgement.explanation ? { explanation: judgement.explanation } : {}),
        ...(judgement.judge ? { judge: judgement.judge, judgeError: judgement.judgeError } : {}),
      }
    },
  },
  {
    name: 'research_download',
    description:
      'Download one open-access PDF (URL from athenaeum_find_pdf / athenaeum_search) into the library downloads folder and index it. At most 5 papers per question; a further download is refused. Only public https PDFs are accepted; paywalls, login pages and bot protection are reported, never bypassed.',
    parameters: object({
      url: string({ minLength: 10, maxLength: 2048 }),
      runId: optional(runId()),
      doi: optional(string({ maxLength: 256 })),
      title: optional(string({ maxLength: 500 })),
      provider: optional(string({ maxLength: 64 })),
      landingPage: optional(string({ maxLength: 2048 })),
      license: optional(string({ maxLength: 128 })),
    }),
    meta: meta({ openWorld: true }),
    async run(config, args, context) {
      if (args.runId) await assertCanDownload(config, args.runId)
      let saved
      try {
        const fetched = await fetchPdf(args.url, { signal: context.signal })
        saved = await saveDownload(config, fetched, args)
      } catch (error) {
        const { code, message } = describeError(error, 'DOWNLOAD_FAILED')
        if (args.runId) await recordDownload(config, args.runId, { ok: false, url: args.url, error: `${code}: ${message}` })
        throw error
      }
      if (args.runId)
        await recordDownload(config, args.runId, { ok: true, url: args.url, relPath: saved.relPath, docId: saved.docId })
      const library = await importStep(config, context)
      const manifest = await loadManifest(statePaths(config))
      const doc = manifest.documents[saved.docId]
      return {
        ok: true,
        file: saved.relPath,
        docId: saved.docId,
        alreadyPresent: saved.alreadyPresent,
        status: doc?.status ?? 'queued',
        next: library.next,
      }
    },
  },
  {
    name: 'research_log',
    description:
      'Record an external-search step in the run (mcp_search, candidate_selected, fulltext_check, acquisition_unavailable, external_search_unavailable, note) with the query, candidate metadata or failure reason.',
    parameters: object({
      runId: runId(),
      stage: enumeration(...LOG_STAGES),
      detail: string({ minLength: 1, maxLength: 4000 }),
    }),
    meta: meta(),
    run: (config, args) => logStage(config, args),
  },
  {
    name: 'research_status',
    description: 'Show a run: state, claims with evidence counts, downloads and every evidence record with its judgement.',
    parameters: object({ runId: runId() }),
    meta: meta({ readOnly: true, replay: 'safe' }),
    async run(config, args) {
      return runSummary(await getRun(config, args.runId), config.jev.threshold)
    },
  },
  {
    name: 'research_finish',
    description:
      'Finish a run with an outcome (answered, insufficient, conflict, acquisition_unavailable, failed, cancelled). answered is refused unless research_judge passed for every verified quote together and the relation is not conditional. conflict is refused unless that same judgement passed with relation conditional. Returns the evidence table and the one pooled judgement.',
    parameters: object({
      runId: runId(),
      outcome: enumeration(...OUTCOMES),
      summary: optional(string({ maxLength: 4000 })),
    }),
    meta: meta({ replay: 'idempotent' }),
    run: (config, args) => finishRun(config, args),
  },
]

export const researchTools = {
  inject: ['extension'],
  apply(ctx) {
    for (const tool of tools)
      ctx.extension().registerTool({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        meta: tool.meta,
        async execute(args, context) {
          try {
            context.signal.throwIfAborted()
            const config = await loadConfig()
            return text(await tool.run(config, args, context))
          } catch (error) {
            return failure(error)
          }
        },
      })
  },
}
