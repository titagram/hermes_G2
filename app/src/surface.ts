export type SurfaceItemType = 'data' | 'action' | 'voice'
export type SurfaceRisk = 'read_only' | 'confirm' | 'dangerous'

export type SurfaceItem = {
  id: string
  type: SurfaceItemType
  label: string
  summary: string
  detail?: string
  priority: number
  action?: {
    kind: string
    confirm: boolean
    risk: SurfaceRisk
  }
}

export type G2Surface = {
  version: number
  updatedAt: number
  status: {
    agent: string
    connection: string
  }
  items: SurfaceItem[]
}

const DEFAULT_SURFACE: G2Surface = {
  version: 1,
  updatedAt: 0,
  status: { agent: 'unknown', connection: 'unknown' },
  items: [],
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : null
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() : fallback
}

function asNumber(value: unknown, fallback = 0): number {
  const number = typeof value === 'string' ? Number(value) : value
  return typeof number === 'number' && Number.isFinite(number) ? number : fallback
}

function asItemType(value: unknown): SurfaceItemType {
  return value === 'action' || value === 'voice' ? value : 'data'
}

function asRisk(value: unknown): SurfaceRisk {
  if (value === 'dangerous' || value === 'confirm') return value
  return 'read_only'
}

function normalizeLabel(value: unknown, fallback: string): string {
  const label = asString(value, fallback).toUpperCase().replace(/\s+/g, ' ')
  return label.slice(0, 16) || fallback.toUpperCase()
}

function normalizeItem(value: unknown): SurfaceItem | null {
  const source = asRecord(value)
  if (!source) return null
  const id = asString(source.id)
  if (!id) return null
  const action = asRecord(source.action)
  const item: SurfaceItem = {
    id,
    type: asItemType(source.type),
    label: normalizeLabel(source.label, id),
    summary: asString(source.summary),
    detail: asString(source.detail) || undefined,
    priority: asNumber(source.priority),
  }

  if (item.type === 'action') {
    item.action = {
      kind: asString(action?.kind, 'run_prompt'),
      confirm: Boolean(action?.confirm),
      risk: asRisk(action?.risk),
    }
  }

  return item
}

export function normalizeSurface(value: unknown): G2Surface {
  const source = asRecord(value)
  if (!source) return DEFAULT_SURFACE
  const status = asRecord(source.status)
  const items = Array.isArray(source.items)
    ? source.items.map(normalizeItem).filter((item): item is SurfaceItem => item !== null)
    : []

  return {
    version: Math.max(1, Math.round(asNumber(source.version, 1))),
    updatedAt: Math.max(0, Math.round(asNumber(source.updatedAt))),
    status: {
      agent: asString(status?.agent, 'unknown'),
      connection: asString(status?.connection, 'unknown'),
    },
    items: items.sort((a, b) => b.priority - a.priority || a.label.localeCompare(b.label)),
  }
}

export function formatHomeRow(item: SurfaceItem, maxLength = 64): string {
  const row = `${item.label}${item.summary ? ` ${item.summary}` : ''}`.replace(/\s+/g, ' ').trim()
  return row.slice(0, maxLength)
}

export function paginateDetail(item: SurfaceItem, charsPerPage = 220): string[] {
  const content = (item.detail && item.detail.trim())
    ? item.detail.trim()
    : `${item.label}\n\n${item.summary || '(no details)'}`
  const pages: string[] = []
  for (let i = 0; i < content.length; i += charsPerPage) {
    pages.push(content.slice(i, i + charsPerPage))
  }
  return pages.length ? pages : ['(no details)']
}
