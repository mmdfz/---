export function fail(code, message, detail) {
  return Object.assign(new Error(message), { code, ...(detail ? { detail } : {}) })
}

export function describeError(error, fallback = 'RESEARCH_FAILED') {
  return {
    code: typeof error?.code === 'string' ? error.code : fallback,
    // biome-ignore lint/suspicious/noControlCharactersInRegex: keep diagnostics single-line and printable.
    message: String(error?.message ?? error).replace(/[\u0000-\u001f\u007f]/gu, ' ').slice(0, 500),
  }
}
