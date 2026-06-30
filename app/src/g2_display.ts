import {
  formatApprovalOptionRow,
  formatHomeRow,
  type G2Approval,
  type G2Surface,
  type SurfaceItem,
} from './surface.js'

export const DASHBOARD_DIMENSIONS = {
  headerHeight: 36,
  listY: 36,
  listHeight: 212,
  hintY: 248,
  hintHeight: 40,
} as const

export type DashboardView = {
  header: string
  rows: string[]
  hint: string
}

export type VoiceStatus = 'listening' | 'transcribing' | 'stt-error' | 'mic-error' | 'idle'

function clip(text: string, maxLength: number): string {
  return text.replace(/\s+/g, ' ').trim().slice(0, maxLength)
}

function badge(value: string, fallback: string): string {
  const cleaned = clip(value, 16)
  return (cleaned || fallback).toUpperCase()
}

export function cleanForG2(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '[code]')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\b(?:https?|wss?):\/\/\S+/gi, '[link]')
    .replace(/\s+\n/g, '\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
}

function sortedItems(surface: G2Surface): SurfaceItem[] {
  return [...surface.items].sort((a, b) => b.priority - a.priority || a.label.localeCompare(b.label))
}

function usefulTarget(summary: string): string {
  const value = clip(summary, 28)
  if (!value) return ''
  const lower = value.toLowerCase()
  if (lower === 'target not set' || lower === 'set target' || lower === 'not set') return ''
  return value
}

function dashboardTarget(items: SurfaceItem[]): string {
  const targetItem = items.find((item) => item.id === 'htb') ?? items.find((item) => item.id === 'hex_recon')
  return targetItem ? usefulTarget(targetItem.summary) : ''
}

export function buildDashboardView(surface: G2Surface, selectedIndex: number): DashboardView {
  const items = sortedItems(surface)
  const target = dashboardTarget(items)
  const headerParts = [
    `HERMES ${badge(surface.status.connection, 'UNKNOWN')}`,
    badge(surface.status.agent, 'IDLE'),
  ]
  if (target) headerParts.push(target)

  const clampedIndex = Math.min(Math.max(selectedIndex, 0), Math.max(items.length - 1, 0))
  const selected = items[clampedIndex]
  const selectedLabel = selected ? badge(selected.label, selected.id) : 'EMPTY'
  const hint = items.length
    ? `${clampedIndex + 1}/${items.length} ${selectedLabel} | press select | double exit`
    : '0/0 EMPTY | double exit'

  return {
    header: clip(headerParts.join(' | '), 64),
    rows: items.map((item) => formatHomeRow(item, 64)),
    hint: clip(hint, 64),
  }
}

export function buildDashboardFallbackText(view: DashboardView, selectedIndex: number): string {
  const rows = view.rows.length
    ? view.rows.map((row, index) => `${index === selectedIndex ? '>' : ' '} ${row}`).join('\n')
    : 'No actions available.'
  return `${view.header}\n\n${rows}\n\n${view.hint}`
}

export function buildApprovalDecisionText(approval: G2Approval, selectedIndex: number): string {
  const optionLines = approval.options.map((option, index) => {
    const cursor = index === selectedIndex ? '>' : ' '
    return `${cursor} ${formatApprovalOptionRow(option)}`
  })
  const reason = cleanForG2(approval.reason || approval.workflow || 'Confirm operation')
  return [
    `APPROVAL ${badge(approval.risk, 'UNKNOWN')}`,
    cleanForG2(approval.title),
    cleanForG2(approval.target || 'target not set'),
    '',
    reason,
    '',
    ...optionLines,
  ].join('\n').slice(0, 1000)
}

export function buildVoiceStatusText(state: VoiceStatus, timeoutSeconds: number, message = ''): string {
  const seconds = Math.max(0, Math.round(timeoutSeconds))
  if (state === 'listening') return `LISTENING\nSpeak now\n\ntimeout ${seconds}s`
  if (state === 'transcribing') return 'TRANSCRIBING\nPlease wait'
  if (state === 'stt-error') {
    return `STT ERROR\n${cleanForG2(message || 'Voice transcription failed')}\n\ntap/ring retry`
  }
  if (state === 'mic-error') return 'MIC ERROR\nMicrophone did not open\n\ntap/ring retry'
  return 'VOICE READY\npress to talk'
}

export function buildStatusPageText(title: string, lines: string[] = []): string {
  const body = lines.map(cleanForG2).filter(Boolean)
  return [badge(title, 'STATUS'), ...body].join('\n').slice(0, 1000)
}
