import { mkdir, readFile, realpath, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fail } from './errors.mjs'

export const CONFIG_ENV = 'AGNES_RESEARCH_CONFIG'
export const CONFIG_FILE_NAME = 'agnes-research.config.json'
export const DEFAULT_THRESHOLD = 0.9
export const DEFAULT_LIBRARY_NAME = 'paper'
const FRAMEWORK_PACKAGE = 'agnes-harness'
/** chat: OpenAI-compatible `{baseUrl}/chat/completions`; decisions: TypeSafe Decisions API `{baseUrl}/decisions`. */
export const JEV_APIS = Object.freeze(['chat', 'decisions'])

export function configPath(env = process.env) {
  return env[CONFIG_ENV] || join(homedir(), CONFIG_FILE_NAME)
}

/** Read on every tool call so edits apply without reinstalling the plugin snapshot. */
export async function loadConfig(path = configPath()) {
  let raw
  try {
    raw = JSON.parse(await readFile(path, 'utf8'))
  } catch (error) {
    throw fail(
      error?.code === 'ENOENT' ? 'RESEARCH_CONFIG_MISSING' : 'RESEARCH_CONFIG_INVALID',
      error?.code === 'ENOENT'
        ? `Research assistant config not found at ${path}. Copy research-assistant.config.example.json there (or set ${CONFIG_ENV}).`
        : `Research assistant config at ${path} is not valid JSON.`,
    )
  }
  return parseConfig(raw, path)
}

/** The framework checkout running this plugin: the nearest ancestor of the AGH entry script named agnes-harness. */
export async function frameworkRoot(entry = process.argv[1]) {
  if (!entry) return undefined
  for (let dir = dirname(resolve(entry)); ; dir = dirname(dir)) {
    const manifest = await readFile(join(dir, 'package.json'), 'utf8').then(
      (text) => JSON.parse(text),
      () => undefined,
    )
    if (manifest?.name === FRAMEWORK_PACKAGE) return dir
    if (dirname(dir) === dir) return undefined
  }
}

/** `<framework>/paper`, or `~/agnes-paper` when AGH runs outside a framework checkout. */
export async function defaultLibraryDir(entry) {
  const root = await frameworkRoot(entry)
  return root ? join(root, DEFAULT_LIBRARY_NAME) : join(homedir(), 'agnes-paper')
}

export async function parseConfig(raw, path = '<config>', { defaultLibrary = defaultLibraryDir } = {}) {
  const problem = (message) => fail('RESEARCH_CONFIG_INVALID', `${path}: ${message}`)
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) throw problem('expected a JSON object')
  if (raw.libraryDir !== undefined && (typeof raw.libraryDir !== 'string' || !isAbsolute(raw.libraryDir)))
    throw problem('libraryDir must be an absolute folder path')
  const requested = raw.libraryDir ?? (await defaultLibrary())
  let libraryDir
  try {
    if (raw.libraryDir === undefined) await mkdir(requested, { recursive: true })
    libraryDir = await realpath(resolve(requested))
    if (!(await stat(libraryDir)).isDirectory()) throw new Error('not a directory')
  } catch {
    throw problem(`libraryDir ${requested} is not an existing folder`)
  }
  const jev = raw.jev
  if (typeof jev !== 'object' || jev === null) throw problem('jev section is missing')
  let baseUrl
  try {
    baseUrl = new URL(jev.baseUrl)
  } catch {
    throw problem('jev.baseUrl must be a URL such as https://host/v1')
  }
  if (!['https:', 'http:'].includes(baseUrl.protocol)) throw problem('jev.baseUrl must use http or https')
  if (typeof jev.model !== 'string' || !jev.model.trim()) throw problem('jev.model is required')
  if (jev.apiKey !== undefined && typeof jev.apiKey !== 'string') throw problem('jev.apiKey must be a string')
  const api = jev.api ?? 'chat'
  if (!JEV_APIS.includes(api)) throw problem(`jev.api must be one of ${JEV_APIS.join(', ')}`)
  const threshold = jev.threshold ?? DEFAULT_THRESHOLD
  if (typeof threshold !== 'number' || !(threshold >= 0 && threshold <= 1))
    throw problem('jev.threshold must be a number from 0 to 1')
  return Object.freeze({
    path,
    libraryDir,
    stateDir: join(libraryDir, '.research'),
    jev: Object.freeze({
      baseUrl: baseUrl.href.replace(/\/+$/u, ''),
      api,
      apiKey: jev.apiKey ?? '',
      model: jev.model.trim(),
      threshold,
    }),
  })
}
