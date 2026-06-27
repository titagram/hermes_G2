export type G2ModelOption = {
  id: string
  label: string
  active: boolean
}

export type G2ModelFamily = {
  provider: string | null
  current: string | null
  canSet: boolean
  source: string | null
  available: G2ModelOption[]
}

export type G2Info = {
  server: {
    name: string
    version: string
    protocol: number
  }
  capabilities: {
    surface: boolean
    approvals: boolean
    sessionResume: boolean
    audioTranscribe: boolean
    models: boolean
    tts: boolean
  }
  reports: {
    current: {
      label: string
      url: string
      source: string
    } | null
  }
  models: {
    llm: G2ModelFamily
    stt: G2ModelFamily
    tts: G2ModelFamily
  }
}

const EMPTY_MODEL_FAMILY: G2ModelFamily = {
  provider: null,
  current: null,
  canSet: false,
  source: null,
  available: [],
}

export const DEFAULT_G2_INFO: G2Info = {
  server: {
    name: 'unknown',
    version: 'unknown',
    protocol: 0,
  },
  capabilities: {
    surface: false,
    approvals: false,
    sessionResume: false,
    audioTranscribe: false,
    models: false,
    tts: false,
  },
  reports: {
    current: null,
  },
  models: {
    llm: EMPTY_MODEL_FAMILY,
    stt: EMPTY_MODEL_FAMILY,
    tts: EMPTY_MODEL_FAMILY,
  },
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : null
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() : fallback
}

function asNumber(value: unknown, fallback = 0): number {
  const numeric = typeof value === 'string' ? Number(value) : value
  return typeof numeric === 'number' && Number.isFinite(numeric) ? numeric : fallback
}

function asHttpUrl(value: unknown): string {
  const url = asString(value)
  return url.startsWith('https://') || url.startsWith('http://') ? url : ''
}

function normalizeModelOption(value: unknown, current: string | null): G2ModelOption | null {
  const source = asRecord(value)
  const id = asString(source?.id ?? value)
  if (!id) return null
  const label = asString(source?.label, id).slice(0, 64)
  return {
    id,
    label,
    active: Boolean(source?.active) || id === current,
  }
}

function normalizeModelFamily(value: unknown): G2ModelFamily {
  const source = asRecord(value)
  if (!source) return { ...EMPTY_MODEL_FAMILY }
  const current = asString(source.current) || null
  const available = Array.isArray(source.available)
    ? source.available
      .map((item) => normalizeModelOption(item, current))
      .filter((item): item is G2ModelOption => item !== null)
    : []
  if (current && !available.some((item) => item.id === current)) {
    available.unshift({ id: current, label: current, active: true })
  }

  return {
    provider: asString(source.provider) || null,
    current,
    canSet: Boolean(source.canSet),
    source: asString(source.source) || null,
    available,
  }
}

export function normalizeG2Info(value: unknown): G2Info {
  const source = asRecord(value)
  if (!source) return DEFAULT_G2_INFO
  const server = asRecord(source.server)
  const capabilities = asRecord(source.capabilities)
  const reports = asRecord(source.reports)
  const currentReport = asRecord(reports?.current)
  const reportUrl = asHttpUrl(currentReport?.url)
  const models = asRecord(source.models)

  return {
    server: {
      name: asString(server?.name, DEFAULT_G2_INFO.server.name),
      version: asString(server?.version, DEFAULT_G2_INFO.server.version),
      protocol: Math.max(0, Math.round(asNumber(server?.protocol))),
    },
    capabilities: {
      surface: Boolean(capabilities?.surface),
      approvals: Boolean(capabilities?.approvals),
      sessionResume: Boolean(capabilities?.sessionResume),
      audioTranscribe: Boolean(capabilities?.audioTranscribe),
      models: Boolean(capabilities?.models),
      tts: Boolean(capabilities?.tts),
    },
    reports: {
      current: reportUrl ? {
        label: asString(currentReport?.label, 'Open Reports'),
        url: reportUrl,
        source: asString(currentReport?.source, 'bridge'),
      } : null,
    },
    models: {
      llm: normalizeModelFamily(models?.llm),
      stt: normalizeModelFamily(models?.stt),
      tts: normalizeModelFamily(models?.tts),
    },
  }
}

export function formatModelRow(option: G2ModelOption, maxLength = 64): string {
  const row = `${option.label}${option.active ? ' current' : ''}`.replace(/\s+/g, ' ').trim()
  return row.slice(0, maxLength)
}
