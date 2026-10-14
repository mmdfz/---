/**
 * The two workbench modes and the literature workflow dock.
 *
 * A mode is a Host preset: Harness is the profile default, Literature is the `research` recipe the
 * profile allows. The Host owns which tools a preset discloses; this module only selects the preset
 * and renders what the session's own tool calls report. The dock follows the MHS Devices layout: a
 * resizable column on the right that pads the page while it is open.
 */
import type { LocaleService, SessionService, SlotRegistry } from '@agnes/web-client'
import {
  createElement,
  type PointerEvent,
  type ReactNode,
  useEffect,
  useState,
  useSyncExternalStore,
} from 'react'
import {
  deriveResearchFlow,
  isFlowCall,
  parseResearchResult,
  type ResearchCall,
  type ResearchCallStatus,
  type ResearchEvidence,
  type ResearchFlow,
  type ResearchStage,
} from './research-flow.js'

export type WorkbenchMode = 'harness' | 'research'

export interface ModeCatalog {
  readonly harness: string
  readonly research?: string
}

const OWNER = '@agnes/web-research'
const MODE_KEY = 'agnes.workbench.mode'
const OPEN_KEY = 'agnes.research.dock.open'
const WIDTH_KEY = 'agnes.research.dock.width'
const RAIL = 36
const MIN_WIDTH = 340

/** Harness is the profile default; Literature is the allowed research recipe, preferring the default's platform variant. */
export function modeCatalog(
  presets: { default: string; allowed: readonly string[] } | undefined,
): ModeCatalog {
  if (!presets) return { harness: 'standard' }
  const variant = presets.default.endsWith('-windows') ? 'research-windows' : 'research'
  const research = presets.allowed.includes(variant)
    ? variant
    : presets.allowed.find((name) => name === 'research' || name.startsWith('research-'))
  return { harness: presets.default, ...(research ? { research } : {}) }
}

export function modeOfPreset(catalog: ModeCatalog, preset: string | undefined): WorkbenchMode {
  return catalog.research !== undefined && preset === catalog.research ? 'research' : 'harness'
}

export function presetForMode(catalog: ModeCatalog, mode: WorkbenchMode): string {
  return mode === 'research' && catalog.research ? catalog.research : catalog.harness
}

function load(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function save(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // A private window does not remember the layout or the default mode.
  }
}

/** The mode a new conversation starts in: the last one chosen. */
export function rememberedMode(): WorkbenchMode {
  return load(MODE_KEY) === 'research' ? 'research' : 'harness'
}

interface ModeState {
  catalog: ModeCatalog | undefined
  mode: WorkbenchMode
  pending: boolean
}

interface DockState {
  open: boolean
  width: number
}

function createStore<T>(initial: T) {
  let state = initial
  const listeners = new Set<() => void>()
  return {
    get: () => state,
    set(patch: Partial<T>) {
      state = { ...state, ...patch }
      for (const listener of [...listeners]) listener()
    },
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
}

const clampWidth = (width: number) =>
  Math.round(Math.min(Math.max(width, MIN_WIDTH), window.innerWidth * 0.6))

export interface ToolDetailLike {
  call: { args?: unknown }
  result?: { content?: ReadonlyArray<{ type: string; text?: string }>; isError?: boolean }
}

export interface ResearchModeOptions {
  locale: LocaleService
  session: SessionService
  /** Undefined when the session is no longer the one shown. */
  readToolDetail(sessionId: string, callSeq: number, resultSeq: number): Promise<ToolDetailLike | undefined>
  /** Apply the chosen mode to the shown session or the draft; rejects when the Host refuses. */
  select(mode: WorkbenchMode): Promise<void>
}

export interface ResearchModeMount {
  setCatalog(catalog: ModeCatalog): void
  /** The mode of the shown session, or of the draft. */
  setMode(mode: WorkbenchMode): void
  mode(): WorkbenchMode
  dispose(): void
}

type ToolNodeView = {
  kind?: string
  seq?: number
  name?: string
  status?: string
  argsPreview?: string
  resultPreview?: string
  resultSeq?: number
}

const STATUS: Record<string, ResearchCallStatus> = {
  planned: 'planned',
  awaiting_approval: 'running',
  running: 'running',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
}

const textOf = (blocks: ReadonlyArray<{ type: string; text?: string }> | undefined) =>
  (blocks ?? [])
    .filter((block) => block.type === 'text')
    .map((block) => block.text ?? '')
    .join('')

function argsOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

/** Read the shown session's research calls, fetching each settled call's full detail once. */
function useResearchFlow(options: ResearchModeOptions): ResearchFlow | undefined {
  const [flow, setFlow] = useState<ResearchFlow | undefined>()
  useEffect(() => {
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    let reading = false
    let again = false
    const details = new Map<string, Pick<ResearchCall, 'args' | 'result' | 'error'>>()
    const read = async (): Promise<void> => {
      timer = undefined
      if (reading) {
        again = true
        return
      }
      reading = true
      try {
        const sessionId = options.session.sessionId
        if (!sessionId) return setFlow(undefined)
        const projection = (await options.session.projection.read()) as {
          status?: string
          value?: { nodes?: ToolNodeView[] }
        }
        if (!live || projection.status !== 'available') return
        const nodes = (projection.value?.nodes ?? []).filter(
          (node) => node.kind === 'tool' && typeof node.name === 'string' && typeof node.seq === 'number',
        )
        const calls: ResearchCall[] = []
        for (const node of nodes) {
          const preview = argsOf(parseResearchResult(node.argsPreview))
          const name = node.name as string
          if (!isFlowCall({ name, args: preview })) continue
          const status = STATUS[node.status ?? ''] ?? 'running'
          const key = `${sessionId}:${node.seq}:${node.resultSeq ?? ''}`
          let detail = details.get(key)
          if (!detail && node.resultSeq !== undefined) {
            const read = await options
              .readToolDetail(sessionId, node.seq as number, node.resultSeq)
              .catch(() => undefined)
            if (!live || options.session.sessionId !== sessionId) return
            if (read) {
              const text = textOf(read.result?.content)
              detail = {
                args: argsOf(read.call.args),
                ...(read.result?.isError ? { error: text } : { result: parseResearchResult(text) }),
              }
              details.set(key, detail)
            }
          }
          calls.push({
            seq: node.seq as number,
            name,
            status,
            args: detail?.args ?? preview,
            ...(detail?.result !== undefined ? { result: detail.result } : {}),
            ...(detail?.error !== undefined
              ? { error: detail.error }
              : status === 'failed' && node.resultPreview
                ? { error: node.resultPreview }
                : {}),
          })
        }
        if (live && options.session.sessionId === sessionId) setFlow(deriveResearchFlow(calls))
      } finally {
        reading = false
        if (again && live) {
          again = false
          soon()
        }
      }
    }
    // A turn emits many projection updates; read at most a few times a second.
    const soon = () => {
      timer ??= setTimeout(() => void read(), 400)
    }
    void read()
    const stops = [options.session.subscribe(() => void read()), options.session.projection.subscribe(soon)]
    return () => {
      live = false
      clearTimeout(timer)
      for (const stop of stops) stop()
    }
  }, [options])
  return flow
}

function useLocale(locale: LocaleService): (key: string, vars?: Record<string, string | number>) => string {
  useSyncExternalStore(locale.subscribe, locale.getSnapshot)
  return (key, vars) => locale.t(key, vars)
}

type T = ReturnType<typeof useLocale>

function stageMetric(stage: ResearchStage, t: T): string | undefined {
  const c = (key: string) => stage.counts[key] ?? 0
  const any = Object.keys(stage.counts).length > 0
  if (!any) return undefined
  switch (stage.id) {
    case 'question':
      return t('research.count.claims', { n: c('claims') })
    case 'library':
      return t('research.count.library', {
        indexed: c('indexed'),
        documents: c('documents'),
        pending: c('pending'),
      })
    case 'local':
      return [
        t('research.count.local', { searches: c('searches'), hits: c('hits'), coverage: c('coverage') }),
        ...(c('sufficient') ? [t('research.count.localSufficient')] : []),
      ].join(' · ')
    case 'external':
      return t('research.count.external', { calls: c('calls'), candidates: c('candidates') })
    case 'acquire':
      return t('research.count.acquire', { downloaded: c('downloaded') })
    case 'reading':
      return t('research.count.reading', { passages: c('passages') })
    case 'pool':
      return t('research.count.pool', { total: c('total'), verified: c('verified') })
    case 'judge': {
      const line = t('research.count.judge', {
        passed: c('passed'),
        judged: c('judged'),
        unavailable: c('unavailable'),
      })
      const confidence = stage.counts.confidence
      return confidence === undefined
        ? line
        : `${line} · ${t('research.evidence.confidence', { value: confidence.toFixed(2) })}`
    }
    default:
      return undefined
  }
}

function StageRow({
  stage,
  index,
  threshold,
  t,
}: {
  stage: ResearchStage
  index: number
  threshold?: number
  t: T
}): ReactNode {
  const [open, setOpen] = useState(false)
  const metric = stageMetric(stage, t)
  const expandable = stage.items.length > 0
  return createElement(
    'li',
    { className: 'research-stage', 'data-state': stage.state, 'data-stage': stage.id },
    createElement('span', { className: 'research-stage-node', 'aria-hidden': 'true' }, String(index + 1)),
    createElement(
      'div',
      { className: 'research-stage-body' },
      createElement(
        'button',
        {
          type: 'button',
          className: 'research-stage-head',
          disabled: !expandable,
          'aria-expanded': expandable ? open : undefined,
          onClick: () => setOpen(!open),
        },
        createElement('span', { className: 'research-stage-name' }, t(`research.stage.${stage.id}`)),
        createElement('span', { className: 'research-stage-state' }, t(`research.state.${stage.state}`)),
      ),
      metric ? createElement('div', { className: 'research-stage-metric' }, metric) : null,
      stage.id === 'judge' && stage.counts.confidence !== undefined
        ? createElement(
            'div',
            {
              className: 'research-confidence',
              title: t('research.evidence.confidence', { value: stage.counts.confidence.toFixed(2) }),
            },
            createElement('span', { style: { width: `${Math.round(stage.counts.confidence * 100)}%` } }),
            threshold !== undefined
              ? createElement('i', {
                  style: { left: `${Math.round(threshold * 100)}%` },
                  'aria-hidden': 'true',
                })
              : null,
          )
        : null,
      open && expandable
        ? createElement(
            'ul',
            { className: 'research-stage-items' },
            stage.items.map((item, i) =>
              createElement(
                'li',
                { key: `${i}-${item.label}`, 'data-tone': item.tone },
                createElement('span', { className: 'research-item-label' }, item.label),
                item.detail
                  ? createElement('span', { className: 'research-item-detail' }, item.detail)
                  : null,
              ),
            ),
          )
        : null,
    ),
  )
}

function EvidenceCard({
  item,
  threshold,
  t,
}: {
  item: ResearchEvidence
  threshold?: number
  t: T
}): ReactNode {
  const verdict = item.judgeUnavailable
    ? 'judgeUnavailable'
    : item.verification && item.verification !== 'verified'
      ? 'unverified'
      : item.round === 'pending'
        ? 'pending'
        : item.passed
          ? 'passed'
          : item.round === 'included'
            ? 'included'
            : 'rejected'
  const location =
    item.page !== undefined
      ? t('research.evidence.location', { page: item.page, paragraph: item.paragraph ?? '?' })
      : item.paragraph !== undefined
        ? `¶${item.paragraph}`
        : ''
  return createElement(
    'li',
    { className: 'research-evidence', 'data-verdict': verdict },
    createElement(
      'div',
      { className: 'research-evidence-head' },
      createElement(
        'span',
        { className: 'research-evidence-id' },
        item.claim ? `${item.id} · ${item.claim}` : item.id,
      ),
      item.relation
        ? createElement(
            'span',
            { className: 'research-chip', 'data-relation': item.relation },
            t(`research.relation.${item.relation}`),
          )
        : null,
      createElement('span', { className: 'research-verdict' }, t(`research.evidence.${verdict}`)),
    ),
    item.confidence !== null
      ? createElement(
          'div',
          {
            className: 'research-confidence',
            title: t('research.evidence.confidence', { value: item.confidence.toFixed(2) }),
          },
          createElement('span', { style: { width: `${Math.round(item.confidence * 100)}%` } }),
          threshold !== undefined
            ? createElement('i', {
                style: { left: `${Math.round(threshold * 100)}%` },
                'aria-hidden': 'true',
              })
            : null,
        )
      : null,
    item.quote ? createElement('blockquote', null, item.quote) : null,
    item.answer ? createElement('p', { className: 'research-evidence-answer' }, item.answer) : null,
    createElement(
      'div',
      { className: 'research-evidence-source' },
      [item.document, location].filter(Boolean).join(' · '),
    ),
    item.explanation ? createElement('p', { className: 'research-evidence-note' }, item.explanation) : null,
    item.reusedFrom
      ? createElement(
          'p',
          { className: 'research-evidence-reused' },
          t('research.evidence.reused', { question: item.reusedFrom.question ?? item.reusedFrom.runId }),
        )
      : null,
  )
}

function HistoryView({ flow, t }: { flow: ResearchFlow; t: T }): ReactNode {
  return createElement(
    'section',
    { className: 'research-card research-history' },
    createElement('h3', null, t('research.history.title'), ` (${flow.history.length})`),
    createElement('p', { className: 'research-dim' }, t('research.history.note')),
    createElement(
      'ul',
      { className: 'research-history-list' },
      [...flow.history].reverse().map((entry, index) =>
        createElement(
          'li',
          { key: entry.runId ?? `q${index}` },
          createElement(
            'details',
            null,
            createElement(
              'summary',
              null,
              createElement('span', { className: 'research-history-question' }, entry.question ?? '?'),
              createElement(
                'span',
                { className: 'research-history-meta' },
                [
                  entry.outcome ? t(`research.outcome.${entry.outcome}`) : t('research.history.open'),
                  t('research.history.counts', {
                    documents: entry.documents.length,
                    evidence: entry.evidence.length,
                    passed: entry.evidence.filter((item) => item.passed).length,
                  }),
                ].join(' · '),
              ),
            ),
            entry.documents.length
              ? createElement('p', { className: 'research-history-documents' }, entry.documents.join(' · '))
              : null,
            entry.evidence.length
              ? createElement(
                  'ul',
                  { className: 'research-evidence-list' },
                  entry.evidence.map((item) => createElement(EvidenceCard, { key: item.id, item, t })),
                )
              : null,
          ),
        ),
      ),
    ),
  )
}

function ConfigCard({ flow, t }: { flow: ResearchFlow | undefined; t: T }): ReactNode {
  const config = flow?.config
  if (!config) return null
  const text =
    config.code === 'RESEARCH_CONFIG_MISSING'
      ? t('research.config.missing')
      : t('research.config.invalid', { detail: config.message })
  return createElement(
    'section',
    { className: 'research-card research-config', 'data-tone': 'bad' },
    createElement('h3', null, t('research.config.title')),
    createElement('p', null, text),
  )
}

function FlowView({ flow, t }: { flow: ResearchFlow | undefined; t: T }): ReactNode {
  const stages = flow?.stages ?? deriveResearchFlow([]).stages
  return createElement(
    'div',
    { className: 'research-scroll' },
    createElement(ConfigCard, { flow, t }),
    flow?.question
      ? createElement(
          'section',
          { className: 'research-card research-question' },
          createElement('h3', null, t('research.panel.question')),
          createElement('p', null, flow.question),
          flow.claims.length > 1
            ? createElement(
                'ol',
                { 'aria-label': t('research.panel.claims') },
                flow.claims.map((claim) =>
                  createElement('li', { key: claim.id }, `${claim.id} ${claim.text}`),
                ),
              )
            : null,
          createElement(
            'div',
            { className: 'research-meta' },
            [
              flow.runId ? t('research.panel.run', { id: flow.runId }) : '',
              flow.threshold !== undefined ? t('research.panel.threshold', { value: flow.threshold }) : '',
            ]
              .filter(Boolean)
              .join(' · '),
          ),
        )
      : createElement('p', { className: 'research-idle' }, t('research.panel.idle')),
    createElement(
      'ol',
      { className: 'research-flow' },
      stages.map((stage, index) =>
        createElement(StageRow, {
          key: stage.id,
          stage,
          index,
          t,
          ...(flow?.threshold !== undefined ? { threshold: flow.threshold } : {}),
        }),
      ),
    ),
    createElement(
      'section',
      { className: 'research-card research-pool' },
      createElement('h3', null, t('research.evidence.title'), ` (${flow?.evidence.length ?? 0})`),
      flow?.evidence.length
        ? createElement(
            'ul',
            { className: 'research-evidence-list' },
            flow.evidence.map((item) =>
              createElement(EvidenceCard, {
                key: item.id,
                item,
                ...(flow.threshold !== undefined ? { threshold: flow.threshold } : {}),
                t,
              }),
            ),
          )
        : createElement('p', { className: 'research-dim' }, t('research.evidence.empty')),
    ),
    flow?.history.length ? createElement(HistoryView, { flow, t }) : null,
  )
}

export function mountResearchMode(registry: SlotRegistry, options: ResearchModeOptions): ResearchModeMount {
  const modes = createStore<ModeState>({ catalog: undefined, mode: rememberedMode(), pending: false })
  const dock = createStore<DockState>({
    open: load(OPEN_KEY) !== 'false',
    width: clampWidth(Number(load(WIDTH_KEY)) || window.innerWidth * 0.32),
  })
  const stopDockSave = dock.subscribe(() => {
    save(OPEN_KEY, String(dock.get().open))
    save(WIDTH_KEY, String(dock.get().width))
  })

  function ModeSwitch(): ReactNode {
    const t = useLocale(options.locale)
    const { catalog, mode, pending } = useSyncExternalStore(modes.subscribe, modes.get)
    if (!catalog?.research) return null
    const choose = (next: WorkbenchMode) => {
      if (next === modes.get().mode || modes.get().pending) return
      modes.set({ pending: true })
      options
        .select(next)
        .then(() => {
          save(MODE_KEY, next)
          modes.set({ mode: next })
        })
        .catch(() => undefined)
        .finally(() => modes.set({ pending: false }))
    }
    const option = (value: WorkbenchMode) =>
      createElement(
        'button',
        {
          key: value,
          type: 'button',
          role: 'radio',
          'aria-checked': mode === value,
          'data-mode': value,
          disabled: pending,
          title: t(value === 'research' ? 'research.mode.researchHint' : 'research.mode.harnessHint'),
          onClick: () => choose(value),
        },
        createElement(
          'span',
          null,
          t(value === 'research' ? 'research.mode.research' : 'research.mode.harness'),
        ),
      )
    return createElement(
      'div',
      { className: 'workbench-mode', role: 'radiogroup', 'aria-label': t('research.mode.label') },
      option('harness'),
      option('research'),
    )
  }

  function startDrag(event: PointerEvent): void {
    if (event.button !== 0 || (event.target as HTMLElement).closest('.research-dock-toggle')) return
    event.preventDefault()
    document.body.classList.add('research-dragging')
    const move = (e: globalThis.PointerEvent) =>
      dock.set({ open: true, width: clampWidth(window.innerWidth - e.clientX) })
    const up = () => {
      document.body.classList.remove('research-dragging')
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  function Dock(): ReactNode {
    const t = useLocale(options.locale)
    const flow = useResearchFlow(options)
    const { open, width } = useSyncExternalStore(dock.subscribe, dock.get)
    useEffect(() => {
      document.body.classList.add('research-docked')
      return () => {
        document.body.classList.remove('research-docked')
        document.documentElement.style.removeProperty('--research-w')
      }
    }, [])
    useEffect(() => {
      document.documentElement.style.setProperty('--research-w', `${open ? width : RAIL}px`)
    }, [open, width])
    const outcome = flow?.outcome
    return createElement(
      'section',
      { className: 'research-dock', 'data-open': open, 'aria-label': t('research.panel.title') },
      createElement(
        'div',
        { className: 'research-seam', onPointerDown: startDrag, title: t('research.panel.resize') },
        createElement(
          'button',
          {
            type: 'button',
            className: 'research-dock-toggle',
            'aria-label': t(open ? 'research.panel.close' : 'research.panel.open'),
            onClick: () => dock.set({ open: !open }),
          },
          open ? '›' : '‹',
        ),
      ),
      open
        ? createElement(
            'div',
            { className: 'research-panel' },
            createElement(
              'header',
              { className: 'research-head' },
              createElement('h2', null, t('research.panel.title')),
              outcome
                ? createElement(
                    'span',
                    { className: 'research-outcome', 'data-outcome': outcome },
                    t(`research.outcome.${outcome}`),
                  )
                : null,
            ),
            createElement(FlowView, { flow, t }),
          )
        : createElement('div', { className: 'research-rail-label' }, t('research.panel.title')),
    )
  }

  const removeSwitch = registry.register(
    { name: 'sidebar.footer.action', id: 'builtin-workbench-mode', owner: OWNER, priority: 0 },
    ModeSwitch,
  )
  let removeDock: (() => void) | undefined
  // A lower number wins the single rightbar slot; this one outranks the MHS Devices dock (-1) only
  // while the Literature mode is shown.
  const syncDock = () => {
    const wanted = modes.get().mode === 'research' && modes.get().catalog?.research !== undefined
    if (wanted && !removeDock)
      removeDock = registry.register(
        { name: 'rightbar', id: 'builtin-research-dock', owner: OWNER, priority: -2 },
        Dock,
      )
    else if (!wanted && removeDock) {
      removeDock()
      removeDock = undefined
    }
  }
  const stopSync = modes.subscribe(syncDock)

  return {
    setCatalog(catalog) {
      modes.set({ catalog })
    },
    setMode(mode) {
      if (mode !== modes.get().mode) modes.set({ mode })
    },
    mode: () => modes.get().mode,
    dispose() {
      stopSync()
      stopDockSave()
      removeDock?.()
      removeSwitch()
    },
  }
}
