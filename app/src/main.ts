/**
 * HermesGlass — Even Realities G2 → Hermes Agent
 *
 * A full-featured Even Hub app for Even Realities G2 smart glasses.
 *
 * Screens:
 *   1. CONFIG — Mobile settings for Bridge URL, STT model, input source, and recording timeout.
 *      URL is persisted via bridge.setLocalStorage().
 *   2. CHAT — Main chat screen: connects to bridge, shows status,
 *      receives streaming responses, supports tap pagination.
 *   3. AUDIO — Captures PCM, wraps WAV, transcribes through the bridge, then sends text to Hermes.
 *
 * Navigation:
 *   Tap        → context-dependent (next page / start mic)
 *   Double-tap → back from active view, exit from home/config
 *   Scroll up  → previous page
 *   Scroll down → next page
 */

import {
  waitForEvenAppBridge,
  TextContainerProperty,
  CreateStartUpPageContainer,
  ListContainerProperty,
  ListItemContainerProperty,
  RebuildPageContainer,
  TextContainerUpgrade,
} from '@evenrealities/even_hub_sdk'
import { arrayBufferToBase64, createPcm16Wav, mergePcmChunks, PCM_SAMPLE_RATE, readTranscriptPayload } from './audio'
import {
  type AppConfig,
  type ConnectionProfile,
  type InputMode,
  CONFIG_STORAGE_KEY,
  DEFAULT_CONFIG,
  LEGACY_BRIDGE_URL_KEY,
  activeProfile,
  deleteProfile,
  isInputAllowed,
  normalizeAppConfig,
  parseStoredConfig,
  serializeAppConfig,
  upsertProfile,
} from './config'
import { normalizeHubEvent } from './events'
import {
  APP_RELEASE_LABEL,
  type ConfigHelpField,
  fieldHelp,
  fieldLabel,
} from './mobile_ui'
import {
  type G2Approval,
  type G2Surface,
  type SurfaceItem,
  formatApprovalOptionRow,
  formatHomeRow,
  normalizeApproval,
  normalizeSurface,
  paginateDetail,
} from './surface'
import './styles.css'

// ── Constants ────────────────────────────────────────────────────

const DISPLAY_W = 576
const DISPLAY_H = 288
const BODY_H = 240
const BODY_PAD = 6
const STATUS_H = 28
const STATUS_Y = BODY_H + 4

const CHARS_PER_PAGE = 220
const ENV_BRIDGE_URL = import.meta.env.VITE_BRIDGE_URL?.trim()
const INITIAL_CONFIG = normalizeAppConfig({
  ...DEFAULT_CONFIG,
  bridgeUrl: ENV_BRIDGE_URL && ENV_BRIDGE_URL.length > 5 ? ENV_BRIDGE_URL : DEFAULT_CONFIG.bridgeUrl,
})

// ── State ────────────────────────────────────────────────────────

type Screen = 'config' | 'home' | 'detail' | 'confirm' | 'approval' | 'chat' | 'connecting' | 'error'
type ChatState = 'idle' | 'listening' | 'thinking' | 'streaming' | 'showing' | 'error'
type GlassesLayout = 'text' | 'list'

let screen: Screen = 'config'
let chatState: ChatState = 'idle'
let appConfig = INITIAL_CONFIG
let bridgeClient: HermesBridgeClient
let currentSurface: G2Surface = normalizeSurface(null)
let selectedHomeIndex = 0
let currentApproval: G2Approval | null = null
let selectedApprovalOptionIndex = 0
let pendingConfirmItem: SurfaceItem | null = null
let responseText = ''
let pages: string[] = []
let currentPage = 0
let connected = false
let recording = false
let glassesLayout: GlassesLayout = 'text'
let currentStatusContent = 'Loading...'
let pcmChunks: Uint8Array[] = []
let cleanedUp = false
let renderTimer: number | null = null
let recordingTimer: number | null = null
let eventIdSaveTimer: number | null = null
let audioAttemptId = 0
let audioControlInFlight = 0
let unsubscribeEvents: (() => void) | null = null
let pendingBodyContent: string | null = null
let bridgeQueue: Promise<unknown> = Promise.resolve()

// ── WebView UI ──────────────────────────────────────────────────

const appRoot = document.querySelector<HTMLDivElement>('#app')

function initWebView() {
  if (!appRoot) return
  appRoot.innerHTML = `
    <main class="app-shell">
      <header class="app-header">
        <div>
          <h1 class="app-title">HermesGlass</h1>
          <p class="app-subtitle">Even Realities G2 bridge for Hermes Agent</p>
        </div>
        <div class="header-status">
          <div class="release-pill">${APP_RELEASE_LABEL}</div>
          <div id="webState" class="state-pill">Starting</div>
        </div>
      </header>

      <section class="app-main">
        <section class="panel">
          <div class="panel-body">
            <div class="profile-row">
              <div>
                ${fieldLabel('profileSelect', 'Profile', 'profiles')}
                <select id="profileSelect" class="config-input"></select>
              </div>
              <div>
                ${fieldLabel('profileNameInput', 'Profile name', 'profiles')}
                <input id="profileNameInput" class="config-input" autocomplete="off" spellcheck="false" />
              </div>
            </div>

            ${fieldLabel('bridgeUrlInput', 'Bridge WebSocket URL', 'bridgeUrl')}
            <input id="bridgeUrlInput" class="config-input" autocomplete="off" spellcheck="false" />

            <div class="field-spaced">${fieldLabel('bridgeTokenInput', 'Token', 'token')}</div>
            <input id="bridgeTokenInput" class="config-input" autocomplete="off" spellcheck="false" type="password" />

            <div class="settings-grid">
              <div>
                ${fieldLabel('sttModelInput', 'STT model', 'sttModel')}
                <input id="sttModelInput" class="config-input" autocomplete="off" spellcheck="false" />
              </div>
              <div>
                ${fieldLabel('maxRecordingSecondsInput', 'Recording seconds', 'recording')}
                <input id="maxRecordingSecondsInput" class="config-input" type="number" min="3" max="60" step="1" />
              </div>
              <div>
                ${fieldLabel('inputModeSelect', 'Input source', 'inputMode')}
                <select id="inputModeSelect" class="config-input">
                  <option value="all">Ring and temples</option>
                  <option value="ring">Ring only</option>
                  <option value="temples">Temples only</option>
                </select>
              </div>
              <div>
                ${fieldLabel('hexTargetInput', 'HexStrike target', 'target')}
                <input id="hexTargetInput" class="config-input" autocomplete="off" spellcheck="false" placeholder="10.129.22.74" />
              </div>
              <div>
                ${fieldLabel('hexScopeInput', 'HexStrike scope', 'scope')}
                <input id="hexScopeInput" class="config-input" autocomplete="off" spellcheck="false" placeholder="HTB authorized machine" />
              </div>
            </div>

            <div id="fieldHelpPanel" class="help-panel" hidden></div>

            <details class="action-drawer" open>
              <summary>
                <span>Controls</span>
                <span id="profileMeta" class="drawer-meta">Default</span>
              </summary>
              <div class="button-grid">
                <button id="newProfileButton" class="button secondary" type="button">New Profile</button>
                <button id="saveProfileButton" class="button secondary" type="button">Save Profile</button>
                <button id="deleteProfileButton" class="button secondary danger" type="button">Delete Profile</button>
                <button id="connectButton" class="button" type="button">Save & Connect</button>
                <button id="testBridgeButton" class="button secondary" type="button">Test Bridge</button>
                <button id="testPromptButton" class="button secondary" type="button" disabled>Send Test Prompt</button>
              </div>
            </details>
          </div>
        </section>

        <section class="status-grid">
          <div class="metric">
            <p class="metric-label">Glasses</p>
            <p id="webDisplayStatus" class="metric-value">Waiting for Even Hub bridge</p>
          </div>
          <div class="metric">
            <p class="metric-label">Hermes</p>
            <p id="webConnectionStatus" class="metric-value">Not connected</p>
          </div>
        </section>

        <section class="panel">
          <div class="panel-body">
            <p class="metric-label">Display Preview</p>
            <pre id="webPreview" class="preview">HermesGlass is starting...</pre>
          </div>
        </section>
      </section>
    </main>
  `

  setWebConfig(appConfig)

  document.querySelector<HTMLButtonElement>('#connectButton')
    ?.addEventListener('click', () => connectToConfiguredBridge().catch(reportFatal))
  document.querySelector<HTMLButtonElement>('#newProfileButton')
    ?.addEventListener('click', () => createNewProfileFromForm().catch(reportFatal))
  document.querySelector<HTMLButtonElement>('#saveProfileButton')
    ?.addEventListener('click', () => saveProfileFromForm(false).catch(reportFatal))
  document.querySelector<HTMLButtonElement>('#deleteProfileButton')
    ?.addEventListener('click', () => deleteActiveProfileFromForm().catch(reportFatal))
  document.querySelector<HTMLButtonElement>('#testBridgeButton')
    ?.addEventListener('click', () => testBridgeConfiguration().catch(reportFatal))
  document.querySelector<HTMLButtonElement>('#testPromptButton')
    ?.addEventListener('click', () => sendTestPrompt().catch(reportFatal))
  document.querySelector<HTMLSelectElement>('#profileSelect')
    ?.addEventListener('change', () => switchProfileFromSelect().catch(reportFatal))
  document.querySelectorAll<HTMLButtonElement>('.help-button')
    .forEach((button) => button.addEventListener('click', () => showFieldHelp(button.dataset.helpField)))
}

function setText(selector: string, value: string) {
  const node = document.querySelector<HTMLElement>(selector)
  if (node) node.textContent = value
}

function setWebState(state: string) {
  setText('#webState', state)
}

function setWebConnectionStatus(status: string) {
  setText('#webConnectionStatus', status)
}

function setWebDisplayStatus(status: string) {
  setText('#webDisplayStatus', status)
}

function setWebPreview(content: string) {
  setText('#webPreview', content)
}

function showFieldHelp(rawField: string | undefined) {
  if (!rawField) return
  const panel = document.querySelector<HTMLDivElement>('#fieldHelpPanel')
  if (!panel) return
  const field = rawField as ConfigHelpField
  try {
    panel.textContent = fieldHelp(field)
    panel.hidden = false
  } catch {
    panel.hidden = true
  }
}

function setWebBridgeUrl(url: string) {
  const input = document.querySelector<HTMLInputElement>('#bridgeUrlInput')
  if (input && input.value !== url) input.value = url
}

function readWebConfig(): AppConfig {
  const seconds = document.querySelector<HTMLInputElement>('#maxRecordingSecondsInput')?.value
  const profile = readProfileForm()
  const next = upsertProfile(appConfig, profile, true)
  return normalizeAppConfig({
    ...next,
    bridgeUrl: document.querySelector<HTMLInputElement>('#bridgeUrlInput')?.value,
    bridgeToken: document.querySelector<HTMLInputElement>('#bridgeTokenInput')?.value,
    sttModel: document.querySelector<HTMLInputElement>('#sttModelInput')?.value,
    maxRecordingMs: seconds ? Number(seconds) * 1000 : undefined,
    inputMode: document.querySelector<HTMLSelectElement>('#inputModeSelect')?.value,
    hexTarget: document.querySelector<HTMLInputElement>('#hexTargetInput')?.value,
    hexScope: document.querySelector<HTMLInputElement>('#hexScopeInput')?.value,
  })
}

function setWebConfig(config: AppConfig) {
  renderProfileOptions(config)
  const bridgeUrlInput = document.querySelector<HTMLInputElement>('#bridgeUrlInput')
  const bridgeTokenInput = document.querySelector<HTMLInputElement>('#bridgeTokenInput')
  const profileNameInput = document.querySelector<HTMLInputElement>('#profileNameInput')
  const sttModelInput = document.querySelector<HTMLInputElement>('#sttModelInput')
  const maxRecordingInput = document.querySelector<HTMLInputElement>('#maxRecordingSecondsInput')
  const inputModeSelect = document.querySelector<HTMLSelectElement>('#inputModeSelect')
  const hexTargetInput = document.querySelector<HTMLInputElement>('#hexTargetInput')
  const hexScopeInput = document.querySelector<HTMLInputElement>('#hexScopeInput')
  const selected = activeProfile(config)

  if (profileNameInput) profileNameInput.value = selected.name
  if (bridgeUrlInput) bridgeUrlInput.value = selected.url
  if (bridgeTokenInput) bridgeTokenInput.value = selected.token
  if (sttModelInput) sttModelInput.value = config.sttModel
  if (maxRecordingInput) maxRecordingInput.value = String(Math.round(config.maxRecordingMs / 1000))
  if (inputModeSelect) inputModeSelect.value = config.inputMode
  if (hexTargetInput) hexTargetInput.value = config.hexTarget
  if (hexScopeInput) hexScopeInput.value = config.hexScope
  setText('#profileMeta', `${selected.name} | ${APP_RELEASE_LABEL}`)
}

function renderProfileOptions(config: AppConfig) {
  const select = document.querySelector<HTMLSelectElement>('#profileSelect')
  if (!select) return
  select.innerHTML = config.profiles
    .map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name)}</option>`)
    .join('')
  select.value = config.activeProfileId
}

function readProfileForm(): ConnectionProfile {
  const existing = activeProfile(appConfig)
  return {
    id: existing.id,
    name: document.querySelector<HTMLInputElement>('#profileNameInput')?.value.trim() || existing.name,
    url: document.querySelector<HTMLInputElement>('#bridgeUrlInput')?.value.trim() || existing.url,
    token: document.querySelector<HTMLInputElement>('#bridgeTokenInput')?.value.trim() || '',
    clientSessionId: existing.clientSessionId || createClientSessionId(),
    lastSeenEventId: existing.lastSeenEventId || 0,
  }
}

function createClientSessionId(): string {
  const rawId = window.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `g2s-${rawId}`.replace(/[^a-zA-Z0-9._:-]/g, '-').slice(0, 64)
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char] ?? char))
}

async function switchProfileFromSelect() {
  const selectedId = document.querySelector<HTMLSelectElement>('#profileSelect')?.value
  if (!selectedId) return
  appConfig = normalizeAppConfig({ ...appConfig, activeProfileId: selectedId })
  setWebConfig(appConfig)
  await saveAppConfig(appConfig)
}

async function createNewProfileFromForm() {
  const id = `profile-${Date.now()}`
  const profile: ConnectionProfile = {
    id,
    name: 'New Profile',
    url: activeProfile(appConfig).url,
    token: '',
    clientSessionId: createClientSessionId(),
    lastSeenEventId: 0,
  }
  appConfig = upsertProfile(appConfig, profile, true)
  setWebConfig(appConfig)
  await saveAppConfig(appConfig)
}

async function saveProfileFromForm(connectAfterSave: boolean) {
  appConfig = upsertProfile(appConfig, readProfileForm(), true)
  setWebConfig(appConfig)
  await saveAppConfig(appConfig)
  if (connectAfterSave) await showChatScreen()
}

async function deleteActiveProfileFromForm() {
  appConfig = deleteProfile(appConfig, appConfig.activeProfileId)
  setWebConfig(appConfig)
  await saveAppConfig(appConfig)
}

function setWebConnected(isConnected: boolean) {
  const button = document.querySelector<HTMLButtonElement>('#testPromptButton')
  if (button) button.disabled = !isConnected
}

function reportFatal(err: unknown) {
  console.error('[HG] Fatal:', err)
  setWebState('Error')
  setWebDisplayStatus('Startup error')
  setWebConnectionStatus(err instanceof Error ? err.message : String(err))
}

function enqueueBridgeCall<T>(operation: () => Promise<T>): Promise<T> {
  const next = bridgeQueue.then(operation, operation)
  bridgeQueue = next.catch(() => {})
  return next
}

// Even Hub bridge (lazy)
let _bridge: any = null
async function bridge() {
  if (!_bridge) _bridge = await waitForEvenAppBridge()
  return _bridge
}

// ── WebSocket client (OpenClaw protocol) ─────────────────────────

class HermesBridgeClient {
  private ws: WebSocket | null = null
  private url: string
  private token: string
  private msgId = 0
  private shouldClose = false
  private reconnectTimer: number | null = null
  private reconnectInterval = 1000
  private maxReconnectInterval = 30000
  private pending = new Map<string, {
    resolve: (payload: any) => void
    reject: (error: Error) => void
    timer: number
  }>()

  onConnect: (() => void) | null = null
  onDisconnect: (() => void) | null = null
  onDelta: ((text: string) => void) | null = null
  onFinal: ((text: string) => void) | null = null
  onError: ((msg: string) => void) | null = null
  onEventId: ((eventId: number) => void) | null = null

  constructor(url: string, token = '') {
    this.url = url
    this.token = token
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState === WebSocket.OPEN) { resolve(); return }
      this.shouldClose = false
      try {
        this.ws = new WebSocket(this.url)
        this.ws.onopen = () => {
          this.reconnectInterval = 1000
          this.sendHandshake()
          this.onConnect?.()
          resolve()
        }
        this.ws.onmessage = (e) => this.handleMessage(e.data as string)
        this.ws.onerror = () => { this.onError?.('Connection error'); reject(new Error('WS error')) }
        this.ws.onclose = () => {
          this.ws = null
          this.onDisconnect?.()
          if (!this.shouldClose) this.scheduleReconnect()
        }
      } catch (err) { reject(err) }
    })
  }

  disconnect() {
    this.shouldClose = true
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer)
      pending.reject(new Error('Disconnected'))
      this.pending.delete(id)
    }
    this.ws?.close(); this.ws = null
  }

  private sendHandshake() {
    this.send({ type: 'req', id: this.genId(), method: 'connect', params: {
      minProtocol: 3, maxProtocol: 3,
      client: { id: 'hermes-glass', version: '1.0.0', platform: 'web', mode: 'operator' },
      role: 'operator', scopes: ['operator.read', 'operator.write'],
      token: this.token,
      caps: [], commands: [], permissions: {}, locale: 'en-US', userAgent: 'hermes-glass/1.0.0',
    }})
  }

  private handleMessage(data: string) {
    for (const line of data.split('\n')) {
      if (!line.trim()) continue
      try {
        const msg = JSON.parse(line)
        if (msg.type === 'res') {
          if (msg.payload?.type === 'hello-ok') console.log('[HG] Handshake ok')
          const pending = this.pending.get(msg.id)
          if (pending) {
            clearTimeout(pending.timer)
            this.pending.delete(msg.id)
            if (msg.ok) pending.resolve(msg.payload ?? {})
            else pending.reject(new Error(msg.error?.message || 'Bridge request failed'))
          }
        } else if (msg.type === 'event') {
          this.handleEvent(msg.event, msg.payload ?? {})
        }
      } catch (e) { console.error('[HG] Parse error:', e) }
    }
  }

  private handleEvent(eventName: string, payload: any) {
    const eventId = typeof payload?.eventId === 'number' ? payload.eventId : Number(payload?.eventId)
    if (Number.isFinite(eventId) && eventId > 0) this.onEventId?.(Math.round(eventId))
    if (eventName === 'chat.event') {
      if (payload.state === 'delta') this.onDelta?.(payload.message?.content || '')
      else if (payload.state === 'final') this.onFinal?.(payload.message?.content || '')
      else if (payload.state === 'error') this.onError?.(payload.errorMessage || 'Unknown error')
    }
  }

  sendChat(message: string, sessionKey = 'g2-hermes') {
    this.send({ type: 'req', id: this.genId(), method: 'chat.send', params: { sessionKey, message, idempotencyKey: `s_${Date.now()}` } })
  }

  async getBridgeCapabilities(): Promise<Record<string, unknown>> {
    return this.sendRequest('bridge.capabilities', {}, 10000)
  }

  async getSurface(): Promise<G2Surface> {
    return normalizeSurface(await this.sendRequest('g2.surface.get', {}, 10000))
  }

  async refreshSurface(): Promise<G2Surface> {
    return normalizeSurface(await this.sendRequest('g2.surface.refresh', {}, 10000))
  }

  async resumeSession(
    clientSessionId: string,
    profileId: string,
    lastSeenEventId: number,
    target: string,
    scope: string,
  ): Promise<Record<string, unknown>> {
    const payload = await this.sendRequest('g2.session.resume', {
      clientSessionId,
      profileId,
      lastSeenEventId,
      target,
      scope,
    }, 10000)
    this.replayMissedEvents(payload)
    return payload
  }

  private replayMissedEvents(payload: any) {
    const events = Array.isArray(payload?.missedEvents) ? payload.missedEvents : []
    for (const event of events) {
      if (!event || typeof event !== 'object') continue
      const eventName = typeof event.type === 'string' ? event.type : ''
      if (!eventName) continue
      const eventPayload = event.payload && typeof event.payload === 'object'
        ? { ...event.payload }
        : {}
      const eventId = Number(event.eventId)
      if (Number.isFinite(eventId) && eventId > 0) eventPayload.eventId = Math.round(eventId)
      this.handleEvent(eventName, eventPayload)
    }
  }

  async runAction(id: string): Promise<Record<string, unknown>> {
    return this.sendRequest('g2.action.run', { id, sessionKey: 'g2-hermes' }, 30000)
  }

  async setTarget(target: string, scope: string): Promise<Record<string, unknown>> {
    return this.sendRequest('g2.target.set', { target, scope }, 10000)
  }

  async respondApproval(id: string, optionId: string): Promise<Record<string, unknown>> {
    return this.sendRequest('g2.approval.respond', { id, optionId, sessionKey: 'g2-hermes' }, 30000)
  }

  async getBootstrapStatus(): Promise<Record<string, unknown>> {
    return this.sendRequest('g2.bootstrap.status', {}, 10000)
  }

  async transcribeAudio(audioBase64: string, sttModel: string): Promise<string> {
    const payload = await this.sendRequest('audio.transcribe', {
      audioBase64,
      mimeType: 'audio/wav',
      sampleRate: PCM_SAMPLE_RATE,
      sttModel,
    }, 60000)
    return readTranscriptPayload(payload)
  }

  private sendRequest(method: string, params: any, timeoutMs = 30000): Promise<any> {
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        reject(new Error('Bridge is not connected'))
        return
      }

      const id = this.genId()
      const timer = window.setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`${method} timed out`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      this.send({ type: 'req', id, method, params })
    })
  }

  private send(obj: any) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj))
    else console.error('[HG] Cannot send: not connected')
  }

  private genId() { return `msg_${Date.now()}_${++this.msgId}` }
  private scheduleReconnect() {
    if (this.reconnectTimer) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectInterval = Math.min(this.reconnectInterval * 1.5, 30000)
      this.connect().catch(() => {})
    }, this.reconnectInterval)
  }
}

// ── Text utilities ───────────────────────────────────────────────

function cleanForG2(text: string): string {
  return text.replace(/```[\s\S]*?```/g, '[code]').replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\*([^*]+)\*/g, '$1')
    .replace(/https?:\/\/\S+/gi, '[link]').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').trim()
}

function paginate(text: string): string[] {
  if (text.length <= CHARS_PER_PAGE) return [text]
  const paras = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
  const result: string[] = []
  let buf = '', bufLen = 0
  for (const p of paras) {
    const cost = p.length + (buf ? 2 : 0)
    if (bufLen + cost > CHARS_PER_PAGE && buf) { result.push(buf); buf = p; bufLen = p.length }
    else { buf = buf ? `${buf}\n\n${p}` : p; bufLen += cost }
  }
  if (buf) result.push(buf)
  const final: string[] = []
  for (const page of result) {
    if (page.length <= CHARS_PER_PAGE) final.push(page)
    else for (let i = 0; i < page.length; i += CHARS_PER_PAGE) final.push(page.slice(i, i + CHARS_PER_PAGE))
  }
  return final
}

// ── Display helpers ──────────────────────────────────────────────

function buildTextPage(bodyContent: string, statusContent: string, capture = 1) {
  const body = new TextContainerProperty({
    xPosition: 0, yPosition: 0, width: DISPLAY_W, height: BODY_H,
    borderWidth: 0, borderColor: 5, paddingLength: BODY_PAD,
    containerID: 1, containerName: 'body',
    content: bodyContent,
    isEventCapture: capture,
  })
  const status = new TextContainerProperty({
    xPosition: 0, yPosition: STATUS_Y, width: DISPLAY_W, height: STATUS_H,
    borderWidth: 0, borderColor: 5, paddingLength: 4,
    containerID: 2, containerName: 'status',
    content: statusContent,
    isEventCapture: capture ? 0 : 1,
  })
  return { containerTotalNum: 2, textObject: [body, status] }
}

async function rebuildTextLayout(bodyContent: string, statusContent: string) {
  pendingBodyContent = null
  if (renderTimer !== null) {
    clearTimeout(renderTimer)
    renderTimer = null
  }
  currentStatusContent = statusContent
  glassesLayout = 'text'
  setWebPreview(bodyContent)
  setWebDisplayStatus(statusContent)
  await enqueueBridgeCall(async () => {
    const b = await bridge()
    await b.rebuildPageContainer(new RebuildPageContainer(buildTextPage(bodyContent, statusContent)))
  })
}

async function updateBody(content: string) {
  if (glassesLayout !== 'text') {
    await rebuildTextLayout(content, currentStatusContent)
    return
  }
  pendingBodyContent = content
  setWebPreview(content)
  if (renderTimer !== null) return
  renderTimer = window.setTimeout(async () => {
    const nextContent = pendingBodyContent ?? ''
    pendingBodyContent = null
    renderTimer = null
    await enqueueBridgeCall(async () => {
      const b = await bridge()
      await b.textContainerUpgrade(new TextContainerUpgrade({
        containerID: 1,
        containerName: 'body',
        contentOffset: 0,
        contentLength: 0,
        content: nextContent,
      }))
    })
  }, 120)
}

async function updateStatus(content: string) {
  currentStatusContent = content
  if (glassesLayout !== 'text') {
    setWebDisplayStatus(content)
    return
  }
  setWebDisplayStatus(content)
  await enqueueBridgeCall(async () => {
    const b = await bridge()
    await b.textContainerUpgrade(new TextContainerUpgrade({
      containerID: 2,
      containerName: 'status',
      contentOffset: 0,
      contentLength: 0,
      content,
    }))
  })
}

function buildHomeText(surface: G2Surface): string {
  if (surface.items.length === 0) return 'Hermes\n\nNo actions available.'
  return surface.items
    .map((item, index) => `${index === selectedHomeIndex ? '>' : ' '} ${formatHomeRow(item)}`)
    .join('\n')
}

function buildApprovalText(approval: G2Approval): string {
  const lines = [
    'APPROVAL',
    approval.title,
    approval.target || 'target not set',
    `risk ${approval.risk}`,
    '',
    ...approval.options.map((option, index) => (
      `${index === selectedApprovalOptionIndex ? '>' : ' '} ${formatApprovalOptionRow(option)}`
    )),
  ]
  return lines.join('\n')
}

async function renderHomeSurface(surface: G2Surface) {
  screen = 'home'
  chatState = 'idle'
  currentSurface = surface
  selectedHomeIndex = Math.min(selectedHomeIndex, Math.max(surface.items.length - 1, 0))
  currentApproval = null
  selectedApprovalOptionIndex = 0
  pendingConfirmItem = null
  setWebState('Home')
  setWebConnectionStatus(`Connected to ${activeProfile(appConfig).name}`)
  setWebConnected(true)

  const rows = surface.items.map((item) => formatHomeRow(item))
  const status = `${surface.status.agent} | press: select | double: exit`
  currentStatusContent = status
  setWebPreview(buildHomeText(surface))
  setWebDisplayStatus(status)

  if (rows.length === 0) {
    await rebuildTextLayout('Hermes\n\nNo actions available.', status)
    return
  }

  try {
    await enqueueBridgeCall(async () => {
      const b = await bridge()
      await b.rebuildPageContainer(new RebuildPageContainer({
        containerTotalNum: 2,
        listObject: [new ListContainerProperty({
          xPosition: 0, yPosition: 0, width: DISPLAY_W, height: BODY_H,
          borderWidth: 0, borderColor: 5, paddingLength: BODY_PAD,
          containerID: 1, containerName: 'home',
          itemContainer: new ListItemContainerProperty({
            itemCount: rows.length,
            itemWidth: 0,
            isItemSelectBorderEn: 1,
            itemName: rows,
          }),
          isEventCapture: 1,
        })],
        textObject: [new TextContainerProperty({
          xPosition: 0, yPosition: STATUS_Y, width: DISPLAY_W, height: STATUS_H,
          borderWidth: 0, borderColor: 5, paddingLength: 4,
          containerID: 2, containerName: 'status',
          content: status,
          isEventCapture: 0,
        })],
      }))
    })
    glassesLayout = 'list'
  } catch (err) {
    console.warn('[HG] Native list render failed, using text fallback:', err)
    await rebuildTextLayout(buildHomeText(surface), status)
  }
}

async function showApproval(approval: G2Approval) {
  screen = 'approval'
  chatState = 'idle'
  currentApproval = approval
  selectedApprovalOptionIndex = Math.min(selectedApprovalOptionIndex, Math.max(approval.options.length - 1, 0))
  setWebState('Approval')
  await rebuildTextLayout(
    buildApprovalText(approval),
    'Approval | press: choose | double: back'
  )
}

async function refreshSurfaceAndRender() {
  if (!bridgeClient || !connected) return
  const surface = await bridgeClient.getSurface()
  await renderHomeSurface(surface)
}

async function updateBodyIfGlassesReady(content: string) {
  if (audioControlInFlight > 0) {
    setWebPreview(content)
    return
  }
  await updateBody(content)
}

async function updateStatusIfGlassesReady(content: string) {
  if (audioControlInFlight > 0) {
    setWebDisplayStatus(content)
    return
  }
  await updateStatus(content)
}

async function showConfigScreen() {
  screen = 'config'
  setWebState('Setup')
  setWebConfig(appConfig)
  setWebConnectionStatus('Ready to connect')
  await updateBody(
    `HERMESGLASS SETUP\n\nConfigure on phone screen.\nBridge:\n${appConfig.bridgeUrl}\n\nTap/ring: connect | Double-tap: exit`
  )
  await updateStatus(`Config | ${appConfig.inputMode} | ${Math.round(appConfig.maxRecordingMs / 1000)}s`)
}

async function showChatScreen() {
  screen = 'connecting'
  chatState = 'idle'
  const profile = activeProfile(appConfig)
  setWebState('Connecting')
  setWebConnectionStatus(`Connecting to ${profile.name}`)
  setWebConnected(false)
  await rebuildTextLayout('HermesGlass\n\nConnecting...', 'Connecting...')
  await updateStatus('Connecting...')

  bridgeClient?.disconnect()
  bridgeClient = new HermesBridgeClient(profile.url, profile.token)

  bridgeClient.onConnect = async () => {
    connected = true
    setWebState('Connected')
    setWebConnectionStatus(`Connected to ${profile.name}`)
    setWebConnected(true)
    try {
      bridgeClient.onEventId = rememberBridgeEventId
      try {
        await bridgeClient.resumeSession(
          profile.clientSessionId,
          profile.id,
          profile.lastSeenEventId || appConfig.lastSeenEventId,
          appConfig.hexTarget,
          appConfig.hexScope,
        )
      } catch (resumeErr) {
        console.warn('[HG] G2 session resume failed, falling back to target set:', resumeErr)
        await bridgeClient.setTarget(appConfig.hexTarget, appConfig.hexScope)
      }
      const surface = await bridgeClient.getSurface()
      await renderHomeSurface(surface)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      await rebuildTextLayout(`HermesGlass\n\nConnected, but surface failed:\n${cleanForG2(msg)}`, 'Surface error')
    }
  }

  bridgeClient.onDisconnect = async () => {
    connected = false
    setWebState('Reconnecting')
    setWebConnectionStatus('Disconnected. Reconnecting...')
    setWebConnected(false)
    await rebuildTextLayout('HermesGlass\n\nDisconnected.\nReconnecting...', 'Reconnecting...')
    await updateStatus('Reconnecting...')
  }

  bridgeClient.onDelta = async (text: string) => {
    if (chatState !== 'streaming' && chatState !== 'thinking') chatState = 'streaming'
    const clean = cleanForG2(text)
    pages = paginate(clean)
    currentPage = 0
    setWebState('Streaming')
    await updateBody(pages[0] || clean)
  }

  bridgeClient.onFinal = async (text: string) => {
    const clean = cleanForG2(text)
    responseText = clean
    pages = paginate(clean)
    currentPage = 0
    await updateBody(pages[0] || '(no response)')
    chatState = pages.length > 1 ? 'showing' : 'idle'
    setWebState('Connected')
    const s = pages.length > 1
      ? `Page 1/${pages.length} | tap: next | double: back`
      : 'Idle | tap: ask | double: back'
    await updateStatus(s)
  }

  bridgeClient.onError = async (msg: string) => {
    chatState = 'idle'
    setWebState('Error')
    setWebConnectionStatus(msg)
    setWebConnected(false)
    await updateBody(`HermesGlass\n\nError: ${msg}`)
    await updateStatus('Error | tap: retry')
  }

  bridgeClient.connect().catch((err: Error) => {
    console.error('[HG] Initial connect failed:', err)
    updateBody(`HermesGlass\n\nConnection failed.\nCheck bridge URL in settings.\nDouble-tap to exit.`).catch(() => {})
    updateStatus('Error').catch(() => {})
  })
}

async function connectToConfiguredBridge() {
  const nextConfig = readWebConfig()
  await saveAppConfig(nextConfig)
  await showChatScreen()
}

async function saveAppConfig(nextConfig: AppConfig) {
  const b = await bridge()
  appConfig = normalizeAppConfig(nextConfig)
  setWebConfig(appConfig)
  await b.setLocalStorage(CONFIG_STORAGE_KEY, serializeAppConfig(appConfig))
  await b.setLocalStorage(LEGACY_BRIDGE_URL_KEY, appConfig.bridgeUrl)
}

function rememberBridgeEventId(eventId: number) {
  if (!Number.isFinite(eventId) || eventId <= appConfig.lastSeenEventId) return
  const activeId = appConfig.activeProfileId
  const profiles = appConfig.profiles.map((profile) => (
    profile.id === activeId ? { ...profile, lastSeenEventId: eventId } : profile
  ))
  appConfig = normalizeAppConfig({ ...appConfig, profiles, lastSeenEventId: eventId })
  if (eventIdSaveTimer !== null) return
  eventIdSaveTimer = window.setTimeout(() => {
    eventIdSaveTimer = null
    persistLastSeenEventId().catch((err) => {
      console.warn('[HG] Failed to persist last seen event id:', err)
    })
  }, 400)
}

async function persistLastSeenEventId() {
  const b = await bridge()
  await b.setLocalStorage(CONFIG_STORAGE_KEY, serializeAppConfig(appConfig))
}

async function loadAppConfig(b: any): Promise<AppConfig> {
  const stored = await b.getLocalStorage(CONFIG_STORAGE_KEY)
  if (stored) return parseStoredConfig(stored)

  const legacyBridgeUrl = await b.getLocalStorage(LEGACY_BRIDGE_URL_KEY)
  if (legacyBridgeUrl) return normalizeAppConfig({ ...INITIAL_CONFIG, bridgeUrl: legacyBridgeUrl })
  return INITIAL_CONFIG
}

function inputModeLabel(mode: InputMode): string {
  if (mode === 'ring') return 'ring only'
  if (mode === 'temples') return 'temples only'
  return 'ring+temples'
}

async function testBridgeConfiguration() {
  const nextConfig = readWebConfig()
  await saveAppConfig(nextConfig)
  const profile = activeProfile(appConfig)

  setWebState('Testing')
  setWebConnectionStatus('Testing bridge...')
  await updateBody(`HermesGlass\n\nTesting bridge:\n${profile.name}\n${profile.url}`)
  await updateStatus('Testing bridge...')

  const testClient = new HermesBridgeClient(profile.url, profile.token)
  try {
    await testClient.connect()
    const capabilities = await testClient.getBridgeCapabilities()
    if (capabilities.audioTranscribe === true && capabilities.g2Surface === true) {
      setWebState('Ready')
      setWebConnectionStatus('Bridge connected. G2 surface and STT route available.')
      await updateBody('HermesGlass\n\nBridge OK.\nG2 surface available.\nSave & Connect to start.')
      await updateStatus('Bridge OK | G2 ready')
    } else {
      setWebState('Bridge Old')
      setWebConnectionStatus('Bridge connected, but G2 surface or audio.transcribe is not available.')
      await updateBody('HermesGlass\n\nBridge connected, but G2 surface is not available.\nRestart the updated bridge server.')
      await updateStatus('Bridge old | update server')
    }
  } catch (err) {
    setWebState('Bridge Error')
    const msg = err instanceof Error ? err.message : String(err)
    setWebConnectionStatus(msg)
    await updateBody(`HermesGlass\n\nBridge test failed:\n${cleanForG2(msg)}`)
    await updateStatus('Bridge test failed')
  } finally {
    testClient.disconnect()
  }
}

async function sendTestPrompt() {
  if (!bridgeClient || !connected) {
    await connectToConfiguredBridge()
  }
  chatState = 'thinking'
  setWebState('Thinking')
  await updateBody('HermesGlass\n\nThinking...')
  await updateStatus('Thinking...')
  bridgeClient.sendChat('Say hello in one short sentence.')
}

async function activateHomeIndex(index: number) {
  const item = currentSurface.items[index]
  if (!item) return
  selectedHomeIndex = index

  if (item.type === 'voice') {
    await startVoiceRecording()
    return
  }

  if (item.type === 'data') {
    await showDetailForItem(item)
    return
  }

  if (item.action?.kind === 'approval') {
    await runSurfaceAction(item)
    return
  }

  if (item.action?.confirm || item.action?.risk === 'dangerous' || item.action?.risk === 'confirm') {
    await showConfirmForItem(item)
    return
  }

  await runSurfaceAction(item)
}

async function showDetailForItem(item: SurfaceItem) {
  screen = 'detail'
  chatState = 'showing'
  pages = paginateDetail(item, CHARS_PER_PAGE)
  currentPage = 0
  await rebuildTextLayout(pages[0] || '(no details)', `Detail ${currentPage + 1}/${pages.length} | double: back`)
}

async function showConfirmForItem(item: SurfaceItem) {
  screen = 'confirm'
  pendingConfirmItem = item
  await rebuildTextLayout(
    `Confirm action\n\n${item.label}\n${item.summary}\n\nPress to run.\nDouble press to go back.`,
    'Confirm | press: run'
  )
}

async function runSurfaceAction(item: SurfaceItem) {
  if (!bridgeClient || !connected) {
    await connectToConfiguredBridge()
  }
  screen = 'chat'
  chatState = 'thinking'
  setWebState('Running')
  await rebuildTextLayout(`${item.label}\n\nRunning...`, 'Running action...')

  try {
    const result = await bridgeClient.runAction(item.id)
    if (result.state === 'detail' && result.item && typeof result.item === 'object') {
      await showDetailForItem(normalizeSurface({ items: [result.item] }).items[0])
    } else if (result.state === 'approval') {
      const approval = normalizeApproval(result.approval)
      if (!approval) throw new Error('Invalid approval payload')
      await showApproval(approval)
    } else if (result.state === 'voice') {
      await startVoiceRecording()
    } else if (result.accepted !== true) {
      await rebuildTextLayout(`${item.label}\n\nAction returned without output.`, 'Action complete')
      chatState = 'idle'
    }
  } catch (err) {
    chatState = 'idle'
    screen = 'error'
    const msg = err instanceof Error ? err.message : String(err)
    await rebuildTextLayout(`Action failed:\n${cleanForG2(msg)}`, 'Error | double: back')
  }
}

async function chooseApprovalOption(index: number) {
  if (!currentApproval || !bridgeClient || !connected) return
  const option = currentApproval.options[index]
  if (!option) return

  setWebState('Approval')
  await rebuildTextLayout(
    `${currentApproval.title}\n\n${formatApprovalOptionRow(option)}...`,
    'Sending approval...'
  )

  try {
    const result = await bridgeClient.respondApproval(currentApproval.id, option.id)
    if (result.state === 'detail' && result.item && typeof result.item === 'object') {
      await showDetailForItem(normalizeSurface({ items: [result.item] }).items[0])
      return
    }
    if (result.state === 'denied') {
      await rebuildTextLayout('Approval denied.\n\nDouble press to go back.', 'Denied | double: back')
      screen = 'error'
      return
    }
    if (result.state === 'running' || result.accepted === true) {
      screen = 'chat'
      chatState = 'thinking'
      setWebState('Running')
      await rebuildTextLayout(`${currentApproval.title}\n\nRunning...`, 'Running approved action...')
      return
    }
    await rebuildTextLayout('Approval response returned without action.', 'Approval complete')
  } catch (err) {
    screen = 'error'
    chatState = 'idle'
    const msg = err instanceof Error ? err.message : String(err)
    await rebuildTextLayout(`Approval failed:\n${cleanForG2(msg)}`, 'Error | double: back')
  }
}

async function returnHome() {
  await cancelVoiceRecording()
  if (connected && bridgeClient) {
    try {
      await refreshSurfaceAndRender()
      return
    } catch (err) {
      console.warn('[HG] Surface refresh failed while returning home:', err)
    }
  }
  await showConfigScreen()
}

function appendPcmChunk(pcm: unknown) {
  if (pcm instanceof Uint8Array) {
    pcmChunks.push(new Uint8Array(pcm))
  } else if (pcm instanceof ArrayBuffer) {
    pcmChunks.push(new Uint8Array(pcm.slice(0)))
  } else if (Array.isArray(pcm)) {
    pcmChunks.push(Uint8Array.from(pcm))
  }
}

async function cancelVoiceRecording() {
  if (!recording) return
  recording = false
  audioAttemptId++
  clearRecordingTimer()
  pcmChunks = []
  try {
    const b = await bridge()
    runAudioControl(b, false, 2500).catch(() => {})
  } catch (err) {
    console.warn('[HG] Audio cancel failed:', err)
  }
}

function clearRecordingTimer() {
  if (recordingTimer !== null) {
    clearTimeout(recordingTimer)
    recordingTimer = null
  }
}

function runAudioControl(b: any, enabled: boolean, timeoutMs: number): Promise<boolean> {
  audioControlInFlight++
  return new Promise((resolve) => {
    let settled = false
    let released = false
    const releaseInFlight = () => {
      if (released) return
      released = true
      audioControlInFlight = Math.max(0, audioControlInFlight - 1)
    }
    const finish = (opened: boolean) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      releaseInFlight()
      resolve(opened)
    }
    const timer = window.setTimeout(() => {
      console.warn(`[HG] audioControl(${enabled}) timed out`)
      finish(false)
    }, timeoutMs)

    Promise.resolve()
      .then(() => b.audioControl(enabled))
      .then((opened) => {
        finish(Boolean(opened))
      })
      .catch((err) => {
        console.warn(`[HG] audioControl(${enabled}) failed:`, err)
        finish(false)
      })
  })
}

async function startVoiceRecording() {
  if (!bridgeClient || !connected) {
    await connectToConfiguredBridge()
  }

  const b = await bridge()
  pcmChunks = []
  recording = true
  screen = 'chat'
  chatState = 'listening'
  setWebState('Listening')
  await updateBody('HermesGlass\n\nListening...\nTap ring or temple again to send.')
  await updateStatus('Listening | tap/ring: send')

  clearRecordingTimer()
  recordingTimer = window.setTimeout(() => {
    stopVoiceRecordingAndSend().catch(reportFatal)
  }, appConfig.maxRecordingMs)

  const token = ++audioAttemptId
  window.setTimeout(() => {
    if (token !== audioAttemptId || !recording) return
    runAudioControl(b, true, 5000)
      .then(async (opened) => {
        if (token !== audioAttemptId || !recording) {
          if (opened) runAudioControl(b, false, 2500).catch(() => {})
          return
        }

        if (!opened) {
          recording = false
          clearRecordingTimer()
          chatState = 'idle'
          setWebState('Connected')
          await updateBodyIfGlassesReady('HermesGlass\n\nMicrophone did not open.\nTap ring or temple to try again.')
          await updateStatusIfGlassesReady('Mic error | tap/ring: retry')
        }
      })
      .catch(reportFatal)
  }, 200)
}

async function stopVoiceRecordingAndSend() {
  if (!recording) return
  recording = false
  audioAttemptId++
  clearRecordingTimer()

  const b = await bridge()
  runAudioControl(b, false, 2500).catch(() => {})

  const pcm = mergePcmChunks(pcmChunks)
  pcmChunks = []
  if (pcm.byteLength < 1600) {
    chatState = 'idle'
    setWebState('Connected')
    await updateBodyIfGlassesReady('HermesGlass\n\nNo voice captured.\nTap ring or temple to try again.')
    await updateStatusIfGlassesReady('Idle | tap/ring: speak')
    return
  }

  chatState = 'thinking'
  setWebState('Transcribing')
  await updateBodyIfGlassesReady('HermesGlass\n\nTranscribing voice...')
  await updateStatusIfGlassesReady('Transcribing...')

  try {
    const wav = createPcm16Wav(pcm)
    const transcript = await bridgeClient.transcribeAudio(arrayBufferToBase64(wav), appConfig.sttModel)
    if (!transcript) throw new Error('Empty transcript')

    setWebState('Thinking')
    await updateBodyIfGlassesReady(`You: ${cleanForG2(transcript)}\n\nThinking...`)
    await updateStatusIfGlassesReady('Thinking...')
    bridgeClient.sendChat(transcript)
  } catch (err) {
    chatState = 'idle'
    setWebState('STT Error')
    const msg = err instanceof Error ? err.message : String(err)
    await updateBodyIfGlassesReady(`HermesGlass\n\nVoice transcription failed:\n${cleanForG2(msg)}\n\nTap ring or temple to try again.`)
    await updateStatusIfGlassesReady('STT error | tap/ring: retry')
  }
}

// ── Event handler ────────────────────────────────────────────────

async function handleEvent(event: any) {
  const gesture = normalizeHubEvent(event)

  // Double-tap = back from sub-screens, exit from home/config.
  if (gesture.isDoubleTap) {
    if (screen !== 'home' && screen !== 'config') {
      await returnHome()
      return
    }
    const b = await bridge()
    b.shutDownPageContainer(1)
    return
  }

  // Audio PCM
  const pcm = gesture.audioPcm
  if (pcm && recording) {
    appendPcmChunk(pcm)
    return
  }

  if (screen === 'config') {
    // Config screen: tap = save URL and connect
    if (gesture.isTap || gesture.isScrollDown) await connectToConfiguredBridge()
    return
  }

  if (screen === 'home') {
    if (gesture.isListSelect && gesture.selectedIndex !== null) {
      await activateHomeIndex(gesture.selectedIndex)
      return
    }

    if (gesture.isScrollDown && glassesLayout === 'text' && currentSurface.items.length > 0) {
      selectedHomeIndex = Math.min(selectedHomeIndex + 1, currentSurface.items.length - 1)
      await rebuildTextLayout(buildHomeText(currentSurface), currentStatusContent)
      return
    }

    if (gesture.isScrollUp && glassesLayout === 'text' && currentSurface.items.length > 0) {
      selectedHomeIndex = Math.max(selectedHomeIndex - 1, 0)
      await rebuildTextLayout(buildHomeText(currentSurface), currentStatusContent)
      return
    }

    if (gesture.isTap) {
      await activateHomeIndex(selectedHomeIndex)
      return
    }
  }

  if (screen === 'confirm') {
    if (gesture.isTap && pendingConfirmItem) {
      const item = pendingConfirmItem
      pendingConfirmItem = null
      await runSurfaceAction(item)
    }
    return
  }

  if (screen === 'approval') {
    if (!currentApproval) {
      await returnHome()
      return
    }

    if ((gesture.isTap || gesture.isListSelect) && currentApproval.options.length > 0) {
      const optionIndex = gesture.isListSelect && gesture.selectedIndex !== null
        ? gesture.selectedIndex
        : selectedApprovalOptionIndex
      await chooseApprovalOption(optionIndex)
      return
    }

    if (gesture.isScrollDown && selectedApprovalOptionIndex < currentApproval.options.length - 1) {
      selectedApprovalOptionIndex++
      await rebuildTextLayout(buildApprovalText(currentApproval), currentStatusContent)
      return
    }

    if (gesture.isScrollUp && selectedApprovalOptionIndex > 0) {
      selectedApprovalOptionIndex--
      await rebuildTextLayout(buildApprovalText(currentApproval), currentStatusContent)
      return
    }
  }

  if (screen === 'detail') {
    if ((gesture.isTap || gesture.isScrollDown) && currentPage < pages.length - 1) {
      currentPage++
      await updateBody(pages[currentPage])
      await updateStatus(`Detail ${currentPage + 1}/${pages.length} | double: back`)
      return
    }

    if (gesture.isScrollUp && currentPage > 0) {
      currentPage--
      await updateBody(pages[currentPage])
      await updateStatus(`Detail ${currentPage + 1}/${pages.length} | double: back`)
      return
    }
  }

  if (screen === 'chat') {
    if (gesture.isTap) {
      if ((chatState === 'idle' || chatState === 'listening') && !isInputAllowed(appConfig.inputMode, gesture.eventSource)) {
        await updateStatus(`Input ignored | ${inputModeLabel(appConfig.inputMode)}`)
        return
      }

      switch (chatState) {
        case 'idle':
          await startVoiceRecording()
          break
        case 'listening':
          await stopVoiceRecordingAndSend()
          break
        case 'showing':
          if (currentPage < pages.length - 1) {
            currentPage++
            await updateBody(pages[currentPage])
            await updateStatus(`Page ${currentPage + 1}/${pages.length} | tap: next | double: back`)
          } else {
            chatState = 'idle'
            await updateBody('HermesGlass\n\nEnd.\nTap to ask again.')
            await updateStatus('Idle | tap: ask | double: back')
          }
          break
        case 'error':
          bridgeClient.connect().catch(() => {})
          break
      }
      return
    }

    if (gesture.isScrollDown && chatState === 'showing' && currentPage < pages.length - 1) {
      currentPage++
      await updateBody(pages[currentPage])
      await updateStatus(`Page ${currentPage + 1}/${pages.length} | double: back`)
      return
    }

    if (gesture.isScrollUp && chatState === 'showing' && currentPage > 0) {
      currentPage--
      await updateBody(pages[currentPage])
      await updateStatus(`Page ${currentPage + 1}/${pages.length} | double: back`)
      return
    }
  }

  if (gesture.isSystemExit || gesture.isAbnormalExit) {
    cleanup()
  }
}

function cleanup() {
  if (cleanedUp) return
  cleanedUp = true
  audioAttemptId++
  clearRecordingTimer()
  if (eventIdSaveTimer !== null) {
    clearTimeout(eventIdSaveTimer)
    eventIdSaveTimer = null
    persistLastSeenEventId().catch(() => {})
  }
  if (_bridge && recording) runAudioControl(_bridge, false, 2500).catch(() => {})
  recording = false
  unsubscribeEvents?.()
  unsubscribeEvents = null
  bridgeClient?.disconnect()
}

// ── Main ─────────────────────────────────────────────────────────

async function main() {
  console.log('[HG] Starting...')
  setWebState('Starting')

  // Create containers
  const b = await bridge()
  const body = new TextContainerProperty({
    xPosition: 0, yPosition: 0, width: DISPLAY_W, height: BODY_H,
    borderWidth: 0, borderColor: 5, paddingLength: BODY_PAD,
    containerID: 1, containerName: 'body',
    content: 'HermesGlass\n\nLoading...',
    isEventCapture: 1,
  })
  const status = new TextContainerProperty({
    xPosition: 0, yPosition: STATUS_Y, width: DISPLAY_W, height: STATUS_H,
    borderWidth: 0, borderColor: 5, paddingLength: 4,
    containerID: 2, containerName: 'status',
    content: 'Loading...',
    isEventCapture: 0,
  })

  const page = { containerTotalNum: 2, textObject: [body, status] }
  const created = await b.createStartUpPageContainer(new CreateStartUpPageContainer(page))
  if (created !== 0) {
    console.warn('[HG] createStartUpPageContainer failed, trying rebuild:', created)
    const rebuilt = await b.rebuildPageContainer(new RebuildPageContainer(page))
    if (!rebuilt) {
      console.error('[HG] container setup failed:', created)
      setWebState('Error')
      setWebDisplayStatus(`Container setup failed: ${created}`)
      return
    }
  }

  // Register global event handler
  unsubscribeEvents = b.onEvenHubEvent(handleEvent)
  window.addEventListener('beforeunload', cleanup)

  appConfig = await loadAppConfig(b)
  setWebConfig(appConfig)
  await showConfigScreen()
}

initWebView()
main().catch(reportFatal)
