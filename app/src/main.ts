/**
 * HermesGlass — Even Realities G2 → Hermes Agent
 *
 * A full-featured Even Hub app for Even Realities G2 smart glasses.
 *
 * Screens:
 *   1. CONFIG — On first launch, enter the Bridge WebSocket URL.
 *      URL is persisted via bridge.setLocalStorage().
 *   2. CHAT — Main chat screen: connects to bridge, shows status,
 *      receives streaming responses, supports tap pagination.
 *   3. AUDIO — Mic capture ready (PCM stored, STT upgrade path).
 *
 * Navigation:
 *   Tap        → context-dependent (next page / start mic)
 *   Double-tap → exit app from any screen
 *   Scroll up  → previous page
 *   Scroll down → next page
 */

import {
  waitForEvenAppBridge,
  TextContainerProperty,
  CreateStartUpPageContainer,
  TextContainerUpgrade,
  OsEventTypeList,
} from '@evenrealities/even_hub_sdk'

// ── Constants ────────────────────────────────────────────────────

const DISPLAY_W = 576
const DISPLAY_H = 288
const BODY_H = 240
const BODY_PAD = 6
const STATUS_H = 28
const STATUS_Y = BODY_H + 4

const CHARS_PER_PAGE = 220
const STORAGE_KEY = 'hermesglass_bridge_url'
const DEFAULT_URL = 'wss://titagram.tail005130.ts.net:8448/ws'

// ── State ────────────────────────────────────────────────────────

type Screen = 'config' | 'chat' | 'connecting' | 'error'
type ChatState = 'idle' | 'listening' | 'thinking' | 'streaming' | 'showing' | 'error'

let screen: Screen = 'config'
let chatState: ChatState = 'idle'
let bridgeUrl = DEFAULT_URL
let bridgeClient: HermesBridgeClient
let responseText = ''
let pages: string[] = []
let currentPage = 0
let connected = false
let recording = false
let pcmChunks: ArrayBuffer[] = []
let cleanedUp = false
let renderTimer: number | null = null
let configBuffer = ''
const configUrl = DEFAULT_URL

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
  private msgId = 0
  private shouldClose = false
  private reconnectTimer: number | null = null
  private reconnectInterval = 1000
  private maxReconnectInterval = 30000

  onConnect: (() => void) | null = null
  onDisconnect: (() => void) | null = null
  onDelta: ((text: string) => void) | null = null
  onFinal: ((text: string) => void) | null = null
  onError: ((msg: string) => void) | null = null

  constructor(url: string) { this.url = url }

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
    this.ws?.close(); this.ws = null
  }

  private sendHandshake() {
    this.send({ type: 'req', id: this.genId(), method: 'connect', params: {
      minProtocol: 3, maxProtocol: 3,
      client: { id: 'hermes-glass', version: '1.0.0', platform: 'web', mode: 'operator' },
      role: 'operator', scopes: ['operator.read', 'operator.write'],
      caps: [], commands: [], permissions: {}, locale: 'en-US', userAgent: 'hermes-glass/1.0.0',
    }})
  }

  private handleMessage(data: string) {
    for (const line of data.split('\n')) {
      if (!line.trim()) continue
      try {
        const msg = JSON.parse(line)
        if (msg.type === 'res' && msg.payload?.type === 'hello-ok') {
          console.log('[HG] Handshake ok')
        } else if (msg.type === 'event') {
          if (msg.event === 'chat.event') {
            const p = msg.payload
            if (p.state === 'delta') this.onDelta?.(p.message?.content || '')
            else if (p.state === 'final') this.onFinal?.(p.message?.content || '')
            else if (p.state === 'error') this.onError?.(p.errorMessage || 'Unknown error')
          }
        }
      } catch (e) { console.error('[HG] Parse error:', e) }
    }
  }

  sendChat(message: string, sessionKey = 'g2-hermes') {
    this.send({ type: 'req', id: this.genId(), method: 'chat.send', params: { sessionKey, message, idempotencyKey: `s_${Date.now()}` } })
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

async function updateBody(content: string) {
  if (renderTimer !== null) return
  renderTimer = window.setTimeout(async () => {
    renderTimer = null
    const b = await bridge()
    await b.textContainerUpgrade(new TextContainerUpgrade({ containerID: 1, containerName: 'body', content }))
  }, 120)
}

async function updateStatus(content: string) {
  const b = await bridge()
  await b.textContainerUpgrade(new TextContainerUpgrade({ containerID: 2, containerName: 'status', content }))
}

async function showConfigScreen() {
  screen = 'config'
  const b = await bridge()
  const saved = await b.getLocalStorage(STORAGE_KEY) || DEFAULT_URL
  const url = saved.length > 5 ? saved : DEFAULT_URL
  await updateBody(
    `HERMESGLASS SETUP\n\nBridge URL:\n${url}\n\nTap: connect | Scroll: exit | Double-tap: exit`
  )
  await updateStatus(`Bridge: ${url}`)
}

async function showChatScreen() {
  screen = 'chat'
  await updateBody('HermesGlass\n\nConnecting...')
  await updateStatus('Connecting...')

  bridgeClient = new HermesBridgeClient(bridgeUrl)

  bridgeClient.onConnect = async () => {
    connected = true
    await updateBody('HermesGlass\n\nConnected to Hermes.\nLong-press right temple to talk.\nTap to send query.\nDouble-tap to exit.')
    await updateStatus('Connected | tap: ask | double-tap: exit')
  }

  bridgeClient.onDisconnect = async () => {
    connected = false
    await updateBody('HermesGlass\n\nDisconnected.\nReconnecting...')
    await updateStatus('Reconnecting...')
  }

  bridgeClient.onDelta = async (text: string) => {
    if (chatState !== 'streaming' && chatState !== 'thinking') chatState = 'streaming'
    const clean = cleanForG2(text)
    pages = paginate(clean)
    currentPage = 0
    await updateBody(pages[0] || clean)
  }

  bridgeClient.onFinal = async (text: string) => {
    const clean = cleanForG2(text)
    responseText = clean
    pages = paginate(clean)
    currentPage = 0
    await updateBody(pages[0] || '(no response)')
    chatState = pages.length > 1 ? 'showing' : 'idle'
    const s = pages.length > 1
      ? `Page 1/${pages.length} | tap: next | double-tap: exit`
      : 'Idle | tap: ask | double-tap: exit'
    await updateStatus(s)
  }

  bridgeClient.onError = async (msg: string) => {
    chatState = 'idle'
    await updateBody(`HermesGlass\n\nError: ${msg}`)
    await updateStatus('Error | tap: retry')
  }

  bridgeClient.connect().catch((err: Error) => {
    console.error('[HG] Initial connect failed:', err)
    updateBody(`HermesGlass\n\nConnection failed.\nCheck bridge URL in settings.\nDouble-tap to exit.`).catch(() => {})
    updateStatus('Error').catch(() => {})
  })
}

// ── Event handler ────────────────────────────────────────────────

async function handleEvent(event: any) {
  const sysType = event.sysEvent?.eventType ?? null
  const textType = event.textEvent?.eventType ?? null

  // Double-tap = exit from anywhere
  if (sysType === OsEventTypeList.DOUBLE_CLICK_EVENT || textType === OsEventTypeList.DOUBLE_CLICK_EVENT) {
    const b = await bridge()
    b.shutDownPageContainer(1)
    return
  }

  // Audio PCM
  const pcm = event.audioEvent?.audioPcm
  if (pcm && recording) {
    if (pcm instanceof ArrayBuffer) pcmChunks.push(pcm)
    else if (pcm instanceof Uint8Array) pcmChunks.push(pcm.buffer as ArrayBuffer)
    return
  }

  const isTap = sysType === OsEventTypeList.CLICK_EVENT
  const isScrollDown = textType === OsEventTypeList.SCROLL_BOTTOM_EVENT
  const isScrollUp = textType === OsEventTypeList.SCROLL_TOP_EVENT

  if (screen === 'config') {
    // Config screen: tap = save URL and connect
    if (isTap || isScrollDown) {
      const b = await bridge()
      bridgeUrl = configUrl
      await b.setLocalStorage(STORAGE_KEY, bridgeUrl)
      await showChatScreen()
    }
    return
  }

  if (screen === 'chat') {
    if (isTap) {
      switch (chatState) {
        case 'idle':
          // Send a demo query
          chatState = 'thinking'
          await updateBody('HermesGlass\n\nThinking...')
          await updateStatus('Thinking...')
          bridgeClient.sendChat('Say hello in one short sentence.')
          break
        case 'showing':
          if (currentPage < pages.length - 1) {
            currentPage++
            await updateBody(pages[currentPage])
            await updateStatus(`Page ${currentPage + 1}/${pages.length} | tap: next`)
          } else {
            chatState = 'idle'
            await updateBody('HermesGlass\n\nEnd.\nTap to ask again.')
            await updateStatus('Idle | tap: ask')
          }
          break
        case 'error':
          bridgeClient.connect().catch(() => {})
          break
      }
      return
    }

    if (isScrollDown && chatState === 'showing' && currentPage < pages.length - 1) {
      currentPage++
      await updateBody(pages[currentPage])
      await updateStatus(`Page ${currentPage + 1}/${pages.length}`)
      return
    }

    if (isScrollUp && chatState === 'showing' && currentPage > 0) {
      currentPage--
      await updateBody(pages[currentPage])
      await updateStatus(`Page ${currentPage + 1}/${pages.length}`)
      return
    }
  }

  if (sysType === OsEventTypeList.SYSTEM_EXIT_EVENT || sysType === OsEventTypeList.ABNORMAL_EXIT_EVENT) {
    cleanup()
  }
}

function cleanup() {
  if (cleanedUp) return
  cleanedUp = true
  bridgeClient?.disconnect()
  // Cannot call bridge().audioControl(false) here because bridge() may hang
}

// ── Main ─────────────────────────────────────────────────────────

async function main() {
  console.log('[HG] Starting...')

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

  const created = await b.createStartUpPageContainer(
    new CreateStartUpPageContainer({ containerTotalNum: 2, textObject: [body, status] })
  )
  if (created !== 0) {
    console.error('[HG] createStartUpPageContainer failed:', created)
    return
  }

  // Register global event handler
  const unsubscribe = b.onEvenHubEvent(handleEvent)
  window.addEventListener('beforeunload', cleanup)

  // Start in config screen to show the URL
  const saved = await b.getLocalStorage(STORAGE_KEY)
  if (saved && saved.length > 5) {
    bridgeUrl = saved
    await showChatScreen()
  } else {
    await showConfigScreen()
  }
}

main().catch((err) => console.error('[HG] Fatal:', err))