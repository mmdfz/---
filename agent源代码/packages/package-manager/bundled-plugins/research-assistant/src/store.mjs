import { randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'

export function statePaths(config) {
  const state = config.stateDir
  return {
    state,
    manifest: join(state, 'manifest.json'),
    docs: join(state, 'docs'),
    runs: join(state, 'runs'),
    tmp: join(state, 'tmp'),
    downloads: join(config.libraryDir, 'downloads'),
  }
}

export async function readJson(path, fallback) {
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch (error) {
    if (error?.code === 'ENOENT') return fallback
    throw error
  }
}

/** Replace a file only after its full contents are on disk, so a crash never leaves half a record. */
export async function writeJsonAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true })
  const temporary = `${path}.${randomUUID()}.tmp`
  await writeFile(temporary, JSON.stringify(value), 'utf8')
  for (let attempt = 0; ; attempt++) {
    try {
      await rename(temporary, path)
      return
    } catch (error) {
      // Windows refuses a rename while a reader briefly holds the target open.
      if (attempt >= 4 || !['EPERM', 'EACCES', 'EBUSY'].includes(error?.code)) {
        await rm(temporary, { force: true })
        throw error
      }
      await new Promise((resolve) => setTimeout(resolve, 50 * (attempt + 1)))
    }
  }
}

const locks = new Map()

/** Serialize state mutations per library within this process. */
export function withLock(key, task) {
  const previous = locks.get(key) ?? Promise.resolve()
  const next = previous.then(task, task)
  const settled = next.then(
    () => {},
    () => {},
  )
  locks.set(key, settled)
  settled.then(() => {
    if (locks.get(key) === settled) locks.delete(key)
  })
  return next
}

export function emptyManifest() {
  return { version: 1, revision: 0, files: {}, documents: {} }
}

export const loadManifest = (paths) => readJson(paths.manifest, emptyManifest())
export const saveManifest = (paths, manifest) => writeJsonAtomic(paths.manifest, manifest)
export const docPath = (paths, docId) => join(paths.docs, `${docId}.json`)
export const partialPath = (paths, docId) => join(paths.docs, `${docId}.partial.json`)
export const runPath = (paths, runId) => join(paths.runs, `${runId}.json`)
