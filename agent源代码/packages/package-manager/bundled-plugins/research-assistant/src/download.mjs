import { createHash, randomUUID } from 'node:crypto'
import { lookup } from 'node:dns/promises'
import { access, mkdir, rename, rm, writeFile } from 'node:fs/promises'
import { isIP } from 'node:net'
import { join } from 'node:path'
import { fail } from './errors.mjs'
import { MAX_FILE_BYTES } from './library.mjs'
import { loadManifest, saveManifest, statePaths, withLock } from './store.mjs'

const MAX_REDIRECTS = 5
const REQUEST_TIMEOUT_MS = 60_000

function ipv4Private(address) {
  const [a, b] = address.split('.').map(Number)
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19))
  )
}

export function isPrivateAddress(address) {
  if (isIP(address) === 4) return ipv4Private(address)
  const lower = address.toLowerCase()
  const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/u.exec(lower)
  if (mapped) return ipv4Private(mapped[1])
  return (
    lower === '::' ||
    lower === '::1' ||
    /^f[cd]/u.test(lower) ||
    /^fe[89ab]/u.test(lower) ||
    /^ff/u.test(lower)
  )
}

/** Public https only: no credentials in the URL and no private, loopback or link-local targets. */
export async function checkPublicUrl(url, resolve = lookup) {
  if (url.protocol !== 'https:') throw fail('DOWNLOAD_REJECTED', `Only https URLs are downloaded (${url.protocol}).`)
  if (url.username || url.password) throw fail('DOWNLOAD_REJECTED', 'URLs with credentials are not downloaded.')
  const host = url.hostname.replace(/^\[|\]$/gu, '')
  const addresses = isIP(host) ? [{ address: host }] : await resolve(host, { all: true, verbatim: true })
  if (!addresses.length || addresses.some(({ address }) => isPrivateAddress(address)))
    throw fail('DOWNLOAD_REJECTED', `${url.hostname} resolves to a private or local address.`)
}

/** Fetch an open-access PDF, following a bounded number of re-validated redirects. */
export async function fetchPdf(rawUrl, { signal, fetchImpl = fetch, resolve = lookup } = {}) {
  let url
  try {
    url = new URL(rawUrl)
  } catch {
    throw fail('DOWNLOAD_REJECTED', 'The PDF URL is not a valid URL.')
  }
  for (let hop = 0; ; hop++) {
    await checkPublicUrl(url, resolve)
    const response = await fetchImpl(url, {
      redirect: 'manual',
      signal: AbortSignal.any([signal ?? new AbortController().signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]),
      headers: {
        accept: 'application/pdf,*/*;q=0.5',
        'user-agent': 'AgnesResearchAssistant/0.1 (open-access PDF retrieval)',
      },
    }).catch((error) => {
      if (signal?.aborted) throw fail('RESEARCH_CANCELLED', 'The download was cancelled.')
      throw fail('DOWNLOAD_FAILED', `Request failed: ${String(error?.message ?? error).slice(0, 200)}`)
    })
    if (response.status >= 300 && response.status < 400 && response.headers.get('location')) {
      await response.body?.cancel()
      if (hop >= MAX_REDIRECTS) throw fail('DOWNLOAD_REJECTED', 'Too many redirects.')
      url = new URL(response.headers.get('location'), url)
      continue
    }
    if ([401, 402, 403].includes(response.status)) {
      await response.body?.cancel()
      throw fail(
        'DOWNLOAD_ACCESS_DENIED',
        `HTTP ${response.status}: access is restricted (paywall, login or bot protection). It is not bypassed.`,
      )
    }
    if (!response.ok) {
      await response.body?.cancel()
      throw fail('DOWNLOAD_FAILED', `HTTP ${response.status} from ${url.hostname}.`)
    }
    const declared = Number(response.headers.get('content-length'))
    if (declared > MAX_FILE_BYTES) {
      await response.body?.cancel()
      throw fail('DOWNLOAD_REJECTED', 'The file is larger than 100 MiB.')
    }
    const parts = []
    let size = 0
    for await (const part of response.body ?? []) {
      size += part.byteLength
      if (size > MAX_FILE_BYTES) throw fail('DOWNLOAD_REJECTED', 'The file is larger than 100 MiB.')
      parts.push(part)
    }
    const bytes = Buffer.concat(parts)
    if (!bytes.subarray(0, 1024).includes(Buffer.from('%PDF-')))
      throw fail(
        'DOWNLOAD_NOT_PDF',
        `${url.hostname} returned ${response.headers.get('content-type') ?? 'unknown content'} rather than a PDF (often a landing or paywall page).`,
      )
    return { bytes, finalUrl: url.href, contentType: response.headers.get('content-type') ?? undefined }
  }
}

export function safeFileName(title, url) {
  const base =
    (title || decodeURIComponent(new URL(url).pathname.split('/').pop() || 'paper'))
      .normalize('NFKD')
      .replace(/\.pdf$/iu, '')
      .replace(/[^A-Za-z0-9._-]+/gu, '_')
      .replace(/^[._]+|[._]+$/gu, '')
      .slice(0, 80) || 'paper'
  return `${base}.pdf`
}

const exists = (path) =>
  access(path).then(
    () => true,
    () => false,
  )

/**
 * Save a verified PDF into <library>/downloads without overwriting anything, recording where it
 * came from. Indexing happens through the ordinary library import afterwards.
 */
export async function saveDownload(config, { bytes, finalUrl, contentType }, meta) {
  const paths = statePaths(config)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  return withLock(config.stateDir, async () => {
    const manifest = await loadManifest(paths)
    const known = Object.values(manifest.files).find((file) => file.sha256 === sha256 && file.status === 'linked')
    let relPath = known?.relPath ?? manifest.sources?.[sha256]?.relPath
    if (relPath && !(await exists(join(config.libraryDir, relPath)))) relPath = undefined
    const alreadyPresent = Boolean(relPath)
    if (!relPath) {
      await mkdir(paths.downloads, { recursive: true })
      await mkdir(paths.tmp, { recursive: true })
      let name = safeFileName(meta.title, finalUrl)
      if (await exists(join(paths.downloads, name))) name = name.replace(/\.pdf$/u, `-${sha256.slice(0, 8)}.pdf`)
      const temporary = join(paths.tmp, `${randomUUID()}.pdf`)
      await writeFile(temporary, bytes, { flag: 'wx' })
      try {
        if (await exists(join(paths.downloads, name))) throw fail('DOWNLOAD_REJECTED', 'Target file already exists.')
        await rename(temporary, join(paths.downloads, name))
      } catch (error) {
        await rm(temporary, { force: true })
        throw error
      }
      relPath = `downloads/${name}`
    }
    manifest.sources ??= {}
    manifest.sources[sha256] = {
      url: meta.url,
      finalUrl,
      ...(contentType ? { contentType } : {}),
      ...(meta.doi ? { doi: meta.doi } : {}),
      ...(meta.title ? { title: meta.title } : {}),
      ...(meta.provider ? { provider: meta.provider } : {}),
      ...(meta.landingPage ? { landingPage: meta.landingPage } : {}),
      ...(meta.license ? { license: meta.license } : {}),
      acquisition: 'full_text',
      relPath,
      sha256,
      downloadedAt: new Date().toISOString(),
    }
    const doc = manifest.documents[sha256.slice(0, 16)]
    if (doc) Object.assign(doc, { acquisition: 'downloaded', source: manifest.sources[sha256] })
    manifest.revision++
    await saveManifest(paths, manifest)
    return { relPath, sha256, docId: sha256.slice(0, 16), alreadyPresent }
  })
}
