import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { open, readdir, readFile, realpath, rm, stat } from 'node:fs/promises'
import { basename, extname, join, relative, sep } from 'node:path'
import { Worker } from 'node:worker_threads'
import { buildIndex } from './bm25.mjs'
import { describeError, fail } from './errors.mjs'
import {
  docPath,
  loadManifest,
  partialPath,
  readJson,
  saveManifest,
  statePaths,
  withLock,
  writeJsonAtomic,
} from './store.mjs'
import { chunkPage } from './text.mjs'

export const MAX_FILE_BYTES = 100 * 1024 * 1024
const MAX_DEPTH = 16
const PAGE_STALL_MS = 120_000
const TEXT_EXTENSIONS = new Set(['.txt', '.md', '.markdown'])
const SEARCHABLE = new Set(['indexed', 'partial'])

const isInside = (root, path) => path === root || path.startsWith(root.endsWith(sep) ? root : root + sep)
const toRel = (root, path) => relative(root, path).split(sep).join('/')

/** Resolve a library-relative name to a real path that cannot leave the configured folder. */
export async function libraryFile(config, relPath) {
  if (typeof relPath !== 'string' || !relPath || relPath.includes('\0'))
    throw fail('RESEARCH_PATH_INVALID', 'Expected a file name inside the paper library.')
  const real = await realpath(join(config.libraryDir, relPath))
  if (!isInside(config.libraryDir, real) || isInside(config.stateDir, real))
    throw fail('RESEARCH_PATH_OUTSIDE_LIBRARY', 'The file is outside the configured paper library.')
  return real
}

/** Enumerate regular files without following links; hidden entries and the state folder are skipped. */
export async function scanLibrary(config) {
  const files = [],
    skipped = []
  const walk = async (dir, depth) => {
    if (depth > MAX_DEPTH) {
      skipped.push({ relPath: toRel(config.libraryDir, dir), reason: 'folder nesting too deep' })
      return
    }
    let entries
    try {
      entries = await readdir(dir, { withFileTypes: true })
    } catch (error) {
      skipped.push({ relPath: toRel(config.libraryDir, dir) || '.', reason: `unreadable (${error?.code})` })
      return
    }
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue
      const path = join(dir, entry.name)
      const relPath = toRel(config.libraryDir, path)
      if (entry.isSymbolicLink()) {
        skipped.push({ relPath, reason: 'links and junctions are not followed' })
        continue
      }
      if (entry.isDirectory()) {
        const real = await realpath(path).catch(() => undefined)
        if (!real || !isInside(config.libraryDir, real))
          skipped.push({ relPath, reason: 'folder resolves outside the library' })
        else await walk(path, depth + 1)
        continue
      }
      if (!entry.isFile()) continue
      try {
        const info = await stat(path)
        files.push({ relPath, absPath: path, size: info.size, mtimeMs: info.mtimeMs })
      } catch (error) {
        skipped.push({ relPath, reason: `unreadable (${error?.code})` })
      }
    }
  }
  await walk(config.libraryDir, 0)
  files.sort((a, b) => a.relPath.localeCompare(b.relPath))
  return { files, skipped }
}

async function head(path, length = 1024) {
  const handle = await open(path, 'r')
  try {
    const buffer = Buffer.alloc(length)
    const { bytesRead } = await handle.read(buffer, 0, length, 0)
    return buffer.subarray(0, bytesRead)
  } finally {
    await handle.close()
  }
}

/** File signatures decide the parser; an extension only selects which signature is expected. */
export function detectFormat(relPath, bytes) {
  const ext = extname(relPath).toLowerCase()
  const zip = bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04
  const ole = Buffer.from(bytes.subarray(0, 8)).equals(
    Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]),
  )
  if (ext === '.pdf')
    return bytes.includes(Buffer.from('%PDF-'))
      ? { format: 'pdf' }
      : { unsupported: 'named .pdf but the content is not a PDF' }
  if (ext === '.docx') return zip ? { format: 'docx' } : { unsupported: 'named .docx but is not a Word file' }
  if (ext === '.doc') return ole ? { format: 'doc' } : { unsupported: 'named .doc but is not a Word file' }
  if (TEXT_EXTENSIONS.has(ext)) return { format: 'text' }
  return { unsupported: `${ext || 'files without an extension'} is not supported (PDF, DOCX, DOC, TXT, MD)` }
}

export async function sha256File(path) {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(path)) hash.update(chunk)
  return hash.digest('hex')
}

async function detach(paths, manifest, docId, relPath) {
  const doc = manifest.documents[docId]
  if (!doc) return
  doc.relPaths = doc.relPaths.filter((path) => path !== relPath)
  if (doc.relPaths.length) return
  delete manifest.documents[docId]
  await rm(docPath(paths, docId), { force: true })
  await rm(partialPath(paths, docId), { force: true })
}

/** Bring the manifest in line with the folder; returns whether anything changed. */
async function reconcile(config, paths, manifest, scan) {
  let changed = false
  const present = new Set()
  for (const file of scan.files) {
    present.add(file.relPath)
    const prior = manifest.files[file.relPath]
    if (prior && prior.status !== 'missing' && prior.size === file.size && prior.mtimeMs === file.mtimeMs)
      continue
    changed = true
    const base = { relPath: file.relPath, size: file.size, mtimeMs: file.mtimeMs }
    const detected = detectFormat(file.relPath, await head(file.absPath))
    if (prior?.docId) await detach(paths, manifest, prior.docId, file.relPath)
    if (detected.unsupported) {
      manifest.files[file.relPath] = { ...base, status: 'unsupported', error: detected.unsupported }
      continue
    }
    if (file.size > MAX_FILE_BYTES) {
      manifest.files[file.relPath] = { ...base, status: 'failed', error: 'larger than 100 MiB' }
      continue
    }
    const sha256 = await sha256File(file.absPath)
    const docId = sha256.slice(0, 16)
    const source = manifest.sources?.[sha256]
    manifest.files[file.relPath] = { ...base, status: 'linked', sha256, docId, format: detected.format }
    let doc = manifest.documents[docId]
    if (!doc)
      doc = manifest.documents[docId] = {
        docId,
        displayName: basename(file.relPath),
        relPaths: [],
        format: detected.format,
        status: 'queued',
        contentHash: sha256,
        pageCount: null,
        chunkCount: 0,
        ocrPages: [],
        warnings: [],
        acquisition: source ? 'downloaded' : 'local',
        ...(source ? { source } : {}),
      }
    if (!doc.relPaths.includes(file.relPath)) doc.relPaths.push(file.relPath)
  }
  for (const [relPath, entry] of Object.entries(manifest.files)) {
    if (present.has(relPath) || entry.status === 'missing') continue
    changed = true
    if (entry.docId) await detach(paths, manifest, entry.docId, relPath)
    manifest.files[relPath] = { relPath, status: 'missing', error: 'file no longer in the library' }
  }
  return changed
}

function runWorker({ bytes, format, startPage, totalPages, deadline, signal, onPage }) {
  return new Promise((resolve) => {
    const worker = new Worker(new URL('./parse-worker.mjs', import.meta.url), {
      workerData: { bytes: bytes.buffer, format, startPage, totalPages },
      transferList: [bytes.buffer],
      resourceLimits: { maxOldGenerationSizeMb: 512 },
      stdout: true,
      stderr: true,
    })
    worker.stdout.on('data', () => {})
    worker.stderr.on('data', () => {})
    let settled = false,
      stall
    const finish = (outcome) => {
      if (settled) return
      settled = true
      clearTimeout(stall)
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
      worker.terminate().finally(() => resolve(outcome))
    }
    const armStall = () => {
      clearTimeout(stall)
      stall = setTimeout(() => finish({ kind: 'stalled' }), PAGE_STALL_MS)
    }
    const abort = () => finish({ kind: 'aborted' })
    const timer = setTimeout(() => finish({ kind: 'deadline' }), Math.max(0, deadline - Date.now()))
    signal.addEventListener('abort', abort, { once: true })
    armStall()
    worker.on('message', (message) => {
      if (settled) return
      if (message.type === 'page') {
        armStall()
        onPage(message)
      } else if (message.type === 'done') finish({ kind: 'done' })
      else if (message.type === 'error') finish({ kind: 'error', code: message.code, message: message.message })
    })
    worker.once('error', () =>
      finish({ kind: 'error', code: 'DOCUMENT_WORKER_FAILED', message: 'Parser failed or ran out of memory.' }),
    )
    worker.once('exit', () =>
      finish({ kind: 'error', code: 'DOCUMENT_WORKER_FAILED', message: 'Parser stopped before finishing.' }),
    )
    if (signal.aborted) abort()
  })
}

/** Parse one queued document, resuming page by page across calls; returns false when time ran out. */
async function parseQueued(config, paths, doc, { deadline, signal, progress }) {
  const absPath = await libraryFile(config, doc.relPaths[0])
  if (doc.format === 'text') {
    let text
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(await readFile(absPath)).replace(/^\ufeff/u, '')
    } catch {
      doc.status = 'failed'
      doc.error = 'not valid UTF-8 text'
      return true
    }
    const { chunks } = chunkPage({ docId: doc.docId, page: null, text })
    await writeJsonAtomic(docPath(paths, doc.docId), { docId: doc.docId, chunks })
    Object.assign(doc, { status: chunks.length ? 'indexed' : 'partial', pageCount: null, chunkCount: chunks.length })
    if (!chunks.length) doc.warnings.push('file contains no text')
    return true
  }
  const bytes = new Uint8Array(await readFile(absPath))
  if (createHash('sha256').update(bytes).digest('hex') !== doc.contentHash) {
    // Changed after the scan; the next import rescans it under its new identity.
    doc.status = 'queued'
    return true
  }
  const partial = (await readJson(partialPath(paths, doc.docId), undefined)) ?? {
    nextPage: 1,
    totalPages: undefined,
    section: undefined,
    chunks: [],
    ocrPages: [],
    warnings: [],
  }
  doc.status = 'parsing'
  const complete = async () => {
    await writeJsonAtomic(docPath(paths, doc.docId), { docId: doc.docId, chunks: partial.chunks })
    await rm(partialPath(paths, doc.docId), { force: true })
    Object.assign(doc, {
      status: partial.warnings.length || !partial.chunks.length ? 'partial' : 'indexed',
      pageCount: partial.totalPages ?? null,
      chunkCount: partial.chunks.length,
      ocrPages: partial.ocrPages,
      warnings: partial.warnings.slice(0, 50),
    })
    return true
  }
  for (;;) {
    if (partial.totalPages && partial.nextPage > partial.totalPages) return complete()
    if (Date.now() >= deadline || signal.aborted) break
    const outcome = await runWorker({
      bytes: bytes.slice(),
      format: doc.format,
      startPage: partial.nextPage,
      totalPages: partial.totalPages,
      deadline,
      signal,
      onPage(message) {
        if (message.total) partial.totalPages = message.total
        const page = message.page
        if (message.method === 'error') partial.warnings.push(`page ${page}: ${message.error}`)
        else if (!message.text.trim())
          partial.warnings.push(`page ${page ?? 1}: no text recognized (needs review)`)
        if (message.method === 'ocr') partial.ocrPages.push(page)
        const { chunks, section } = chunkPage({
          docId: doc.docId,
          page,
          text: message.text,
          section: partial.section,
        })
        partial.section = section
        partial.chunks.push(...chunks)
        partial.nextPage = (page ?? 1) + 1
        progress?.(`Indexing ${doc.displayName}: page ${page ?? 1}/${partial.totalPages ?? 1}`)
      },
    })
    if (outcome.kind === 'done') return complete()
    if (outcome.kind === 'error') {
      Object.assign(doc, { status: 'failed', error: `${outcome.code}: ${outcome.message}` })
      await rm(partialPath(paths, doc.docId), { force: true })
      return true
    }
    if (outcome.kind === 'stalled') {
      if (!partial.totalPages) {
        Object.assign(doc, { status: 'failed', error: 'DOCUMENT_READ_TIMEOUT: the parser stopped responding' })
        await rm(partialPath(paths, doc.docId), { force: true })
        return true
      }
      partial.warnings.push(`page ${partial.nextPage}: parsing timed out and was skipped`)
      partial.nextPage++
      if (partial.nextPage > partial.totalPages) return complete()
      continue
    }
    break
  }
  await writeJsonAtomic(partialPath(paths, doc.docId), partial)
  return false
}

export function documentView(doc) {
  return {
    docId: doc.docId,
    name: doc.displayName,
    files: doc.relPaths,
    format: doc.format,
    status: doc.status,
    ...(doc.pageCount ? { pages: doc.pageCount } : {}),
    chunks: doc.chunkCount,
    ...(doc.ocrPages?.length ? { ocrPages: doc.ocrPages.length } : {}),
    ...(doc.warnings?.length ? { warnings: doc.warnings.slice(0, 5) } : {}),
    ...(doc.error ? { error: doc.error } : {}),
    acquisition: doc.acquisition,
  }
}

/**
 * Scan the library and index queued documents until the deadline. Work persists after every
 * document, so a later call continues where this one stopped.
 */
export function importLibrary(config, { deadline, signal, progress }) {
  return withLock(config.stateDir, async () => {
    const paths = statePaths(config)
    const manifest = await loadManifest(paths)
    const scan = await scanLibrary(config)
    if (await reconcile(config, paths, manifest, scan)) {
      manifest.revision++
      await saveManifest(paths, manifest)
    }
    const processed = []
    for (const doc of Object.values(manifest.documents)) {
      if (!['queued', 'parsing'].includes(doc.status)) continue
      if (Date.now() >= deadline || signal.aborted) break
      try {
        await parseQueued(config, paths, doc, { deadline, signal, progress })
      } catch (error) {
        const { code, message } = describeError(error, 'DOCUMENT_UNREADABLE')
        Object.assign(doc, { status: 'failed', error: `${code}: ${message}` })
      }
      if (doc.status !== 'parsing') processed.push(doc.docId)
      manifest.revision++
      await saveManifest(paths, manifest)
    }
    return { manifest, scan, processed }
  })
}

export function librarySummary(manifest, scan) {
  const documents = Object.values(manifest.documents)
  const count = (status) => documents.filter((doc) => doc.status === status).length
  const files = Object.values(manifest.files)
  return {
    documents: documents.length,
    indexed: count('indexed'),
    partial: count('partial'),
    failed: count('failed'),
    pending: count('queued') + count('parsing'),
    unsupportedFiles: files.filter((file) => file.status === 'unsupported').length,
    duplicates: documents.filter((doc) => doc.relPaths.length > 1).map((doc) => doc.relPaths),
    ...(scan?.skipped.length ? { skipped: scan.skipped.slice(0, 20) } : {}),
  }
}

const cache = new Map()

/** BM25 over every searchable document, rebuilt only when the manifest revision moves. */
export async function libraryIndex(config) {
  const paths = statePaths(config)
  const manifest = await loadManifest(paths)
  const cached = cache.get(config.stateDir)
  if (cached?.revision === manifest.revision) return cached
  const chunks = [],
    byId = new Map()
  for (const doc of Object.values(manifest.documents)) {
    if (!SEARCHABLE.has(doc.status)) continue
    const stored = await readJson(docPath(paths, doc.docId), undefined)
    if (!stored) continue
    stored.chunks.forEach((chunk, position) => {
      const entry = { ...chunk, docId: doc.docId }
      chunks.push(entry)
      byId.set(chunk.id, { chunk: entry, doc, position, siblings: stored.chunks })
    })
  }
  const built = { revision: manifest.revision, manifest, index: buildIndex(chunks), byId }
  cache.set(config.stateDir, built)
  return built
}
