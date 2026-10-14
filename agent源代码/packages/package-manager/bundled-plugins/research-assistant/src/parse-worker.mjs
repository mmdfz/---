import { parentPort, workerData } from 'node:worker_threads'

// The bundled engine and OCR data are local; parsing never fetches anything a document names.
globalThis.fetch = async () => {
  throw new Error('Document parsing is offline.')
}

const post = (message) => parentPort.postMessage(message)
const errorMessage = (error) =>
  // biome-ignore lint/suspicious/noControlCharactersInRegex: sanitize parser diagnostics.
  String(error?.message ?? error).replace(/[\u0000-\u001f\u007f]/gu, ' ').slice(0, 300)

try {
  const { parseDocument } = await import('./runtime/engine.mjs')
  const assets = new URL('./runtime/assets/', import.meta.url)
  const bytes = new Uint8Array(workerData.bytes)
  if (workerData.format !== 'pdf') {
    const result = await parseDocument(bytes, { mode: 'text' }, assets)
    post({ type: 'page', page: null, text: result.text, method: 'text' })
  } else {
    let page = workerData.startPage,
      total = workerData.totalPages
    do {
      try {
        const result = await parseDocument(bytes, { page, mode: 'text', ocr: 'auto', language: 'eng' }, assets)
        total ??= Number(/PDF page \d+\/(\d+)/u.exec(result.note)?.[1])
        post({
          type: 'page',
          page,
          total,
          text: result.text,
          method: /OCR/u.test(result.note) ? 'ocr' : 'text',
        })
      } catch (error) {
        // Without a page count the document itself is unreadable (encrypted, damaged, too large).
        if (total === undefined) throw error
        post({ type: 'page', page, total, text: '', method: 'error', error: errorMessage(error) })
      }
      page++
    } while (page <= total)
  }
  post({ type: 'done' })
} catch (error) {
  post({
    type: 'error',
    code:
      error?.code === 'ERR_MODULE_NOT_FOUND'
        ? 'RESEARCH_PARSER_UNAVAILABLE'
        : (error?.code ?? 'DOCUMENT_UNREADABLE'),
    message:
      error?.code === 'ERR_MODULE_NOT_FOUND'
        ? 'Parser payload missing. Rebuild the application (pnpm --filter @agnes/cli build:local), then update the plugin from file:./bundled-plugins/research-assistant.'
        : errorMessage(error),
  })
}
