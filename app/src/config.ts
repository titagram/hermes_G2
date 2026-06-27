export type InputMode = 'all' | 'ring' | 'temples'

export type ConnectionProfile = {
  id: string
  name: string
  url: string
  token: string
  clientSessionId: string
  lastSeenEventId: number
}

export type AppConfig = {
  bridgeUrl: string
  bridgeToken: string
  sttModel: string
  maxRecordingMs: number
  inputMode: InputMode
  hexTarget: string
  hexScope: string
  activeProfileId: string
  lastSeenEventId: number
  profiles: ConnectionProfile[]
}

export const CONFIG_STORAGE_KEY = 'hermesglass_config_v2'
export const LEGACY_BRIDGE_URL_KEY = 'hermesglass_bridge_url'
export const DEFAULT_PROFILE_ID = 'default'

export const DEFAULT_CONFIG: AppConfig = {
  bridgeUrl: 'wss://titagram.tail005130.ts.net:8448/ws',
  bridgeToken: '',
  sttModel: 'whisper-1',
  maxRecordingMs: 15000,
  inputMode: 'all',
  hexTarget: '',
  hexScope: '',
  activeProfileId: DEFAULT_PROFILE_ID,
  lastSeenEventId: 0,
  profiles: [{
    id: DEFAULT_PROFILE_ID,
    name: 'Default',
    url: 'wss://titagram.tail005130.ts.net:8448/ws',
    token: '',
    clientSessionId: 'g2s-default',
    lastSeenEventId: 0,
  }],
}

const MIN_RECORDING_MS = 3000
const MAX_RECORDING_MS = 60000

function isInputMode(value: unknown): value is InputMode {
  return value === 'all' || value === 'ring' || value === 'temples'
}

function normalizeBridgeUrl(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  if (trimmed.startsWith('ws://') || trimmed.startsWith('wss://')) return trimmed
  return fallback
}

function normalizeToken(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function normalizeSttModel(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  return trimmed ? trimmed : fallback
}

function normalizeShortText(value: unknown, maxLength: number): string {
  if (typeof value !== 'string') return ''
  return value.trim().replace(/\s+/g, ' ').slice(0, maxLength)
}

function normalizeRecordingMs(value: unknown, fallback: number): number {
  const numeric = typeof value === 'string' ? Number(value) : value
  if (typeof numeric !== 'number' || !Number.isFinite(numeric)) return fallback
  if (numeric < MIN_RECORDING_MS) return fallback
  return Math.min(Math.round(numeric), MAX_RECORDING_MS)
}

function normalizeEventId(value: unknown): number {
  const numeric = typeof value === 'string' ? Number(value) : value
  if (typeof numeric !== 'number' || !Number.isFinite(numeric) || numeric < 0) return 0
  return Math.round(numeric)
}

function normalizeProfileId(value: unknown, fallback = DEFAULT_PROFILE_ID): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  if (!trimmed) return fallback
  return trimmed.replace(/[^a-zA-Z0-9._-]/g, '-').slice(0, 48) || fallback
}

function normalizeClientSessionId(value: unknown, profileId: string): string {
  const fallback = (`g2s-${profileId}`).replace(/[^a-zA-Z0-9._:-]/g, '-').slice(0, 64) || 'g2s-default'
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  if (!trimmed) return fallback
  return trimmed.replace(/[^a-zA-Z0-9._:-]/g, '-').slice(0, 64) || fallback
}

function normalizeProfileName(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  return trimmed ? trimmed.slice(0, 48) : fallback
}

function normalizeProfile(value: unknown, fallbackUrl: string, fallbackLastSeenEventId = 0): ConnectionProfile | null {
  if (!value || typeof value !== 'object') return null
  const source = value as Record<string, unknown>
  const id = normalizeProfileId(source.id, '')
  if (!id) return null
  const url = normalizeBridgeUrl(source.url, '')
  if (!url) return null
  return {
    id,
    name: normalizeProfileName(source.name, id),
    url,
    token: normalizeToken(source.token),
    clientSessionId: normalizeClientSessionId(source.clientSessionId, id),
    lastSeenEventId: normalizeEventId(source.lastSeenEventId ?? fallbackLastSeenEventId),
  }
}

function normalizeProfiles(
  value: unknown,
  legacyUrl: string,
  legacyToken: string,
  legacyLastSeenEventId: number,
): ConnectionProfile[] {
  const profiles = Array.isArray(value)
    ? value
      .map((profile) => normalizeProfile(profile, legacyUrl, legacyLastSeenEventId))
      .filter((profile): profile is ConnectionProfile => profile !== null)
    : []

  if (profiles.length > 0) return dedupeProfiles(profiles)

  return [{
    id: DEFAULT_PROFILE_ID,
    name: 'Default',
    url: legacyUrl,
    token: legacyToken,
    clientSessionId: 'g2s-default',
    lastSeenEventId: legacyLastSeenEventId,
  }]
}

function dedupeProfiles(profiles: ConnectionProfile[]): ConnectionProfile[] {
  const seen = new Set<string>()
  const result: ConnectionProfile[] = []
  for (const profile of profiles) {
    if (seen.has(profile.id)) continue
    seen.add(profile.id)
    result.push(profile)
  }
  return result
}

export function normalizeAppConfig(value: Partial<AppConfig> | Record<string, unknown> | null | undefined): AppConfig {
  const source = value ?? {}
  const legacyUrl = normalizeBridgeUrl(source.bridgeUrl, DEFAULT_CONFIG.bridgeUrl)
  const legacyToken = normalizeToken(source.bridgeToken)
  const legacyLastSeenEventId = normalizeEventId(source.lastSeenEventId)
  const profiles = normalizeProfiles(source.profiles, legacyUrl, legacyToken, legacyLastSeenEventId)
  const requestedActiveId = normalizeProfileId(source.activeProfileId, profiles[0]?.id ?? DEFAULT_PROFILE_ID)
  const selectedProfile = profiles.find((profile) => profile.id === requestedActiveId) ?? profiles[0]

  return {
    bridgeUrl: selectedProfile?.url ?? legacyUrl,
    bridgeToken: selectedProfile?.token ?? legacyToken,
    sttModel: normalizeSttModel(source.sttModel, DEFAULT_CONFIG.sttModel),
    maxRecordingMs: normalizeRecordingMs(source.maxRecordingMs, DEFAULT_CONFIG.maxRecordingMs),
    inputMode: isInputMode(source.inputMode) ? source.inputMode : DEFAULT_CONFIG.inputMode,
    hexTarget: normalizeShortText(source.hexTarget, 128),
    hexScope: normalizeShortText(source.hexScope, 240),
    activeProfileId: selectedProfile?.id ?? DEFAULT_PROFILE_ID,
    lastSeenEventId: selectedProfile?.lastSeenEventId ?? legacyLastSeenEventId,
    profiles,
  }
}

export function parseStoredConfig(raw: string | null | undefined): AppConfig {
  if (!raw) return DEFAULT_CONFIG
  try {
    return normalizeAppConfig(JSON.parse(raw))
  } catch {
    return DEFAULT_CONFIG
  }
}

export function serializeAppConfig(config: AppConfig): string {
  return JSON.stringify(normalizeAppConfig(config))
}

export function activeProfile(config: AppConfig): ConnectionProfile {
  const normalized = normalizeAppConfig(config)
  return normalized.profiles.find((profile) => profile.id === normalized.activeProfileId) ?? normalized.profiles[0]
}

export function upsertProfile(config: AppConfig, profile: ConnectionProfile, makeActive = false): AppConfig {
  const normalized = normalizeAppConfig(config)
  const nextProfile = normalizeProfile(profile, normalized.bridgeUrl)
  if (!nextProfile) return normalized

  const existingIndex = normalized.profiles.findIndex((item) => item.id === nextProfile.id)
  const profiles = existingIndex >= 0
    ? normalized.profiles.map((item, index) => index === existingIndex ? nextProfile : item)
    : [...normalized.profiles, nextProfile]

  return normalizeAppConfig({
    ...normalized,
    profiles,
    activeProfileId: makeActive ? nextProfile.id : normalized.activeProfileId,
  })
}

export function deleteProfile(config: AppConfig, profileId: string): AppConfig {
  const normalized = normalizeAppConfig(config)
  const id = normalizeProfileId(profileId, '')
  const profiles = normalized.profiles.filter((profile) => profile.id !== id)
  if (profiles.length === 0) return normalizeAppConfig(DEFAULT_CONFIG)
  const activeStillExists = profiles.some((profile) => profile.id === normalized.activeProfileId)
  return normalizeAppConfig({
    ...normalized,
    profiles,
    activeProfileId: activeStillExists ? normalized.activeProfileId : profiles[0].id,
  })
}

export function isInputAllowed(mode: InputMode, eventSource: number | null): boolean {
  if (mode === 'all') return true
  if (mode === 'ring') return eventSource === 2
  return eventSource === 1 || eventSource === 3
}
