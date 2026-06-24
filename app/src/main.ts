/**
 * HermesGlass — Even Realities G2 → Hermes Agent
 *
 * An Even Hub app that runs on Even Realities G2 smart glasses.
 * Uses the Even Hub SDK to render UI on the glasses display, capture
 * voice input from the glasses microphone, and stream responses from
 * a Hermes Agent instance via the HermesGlass WebSocket bridge.
 *
 * Architecture:
 *   Glasses mic → PCM audio → STT (browser) → text → WebSocket bridge
 *                                                              ↓
 *   Glasses display ← text containers ← Hermes response ← Hermes API
 *
 * Voice flow:
 *   1. User long-presses right temple → mic activates
 *   2. PCM audio frames captured via bridge.audioControl(true)
 *   3. Audio sent to browser-based STT (whisper.cpp WASM or cloud)
 *   4. Final transcript sent to Hermes via WebSocket bridge
 *   5. Response streamed back as text container upgrades
 *   6. User taps to advance pages, double-taps to exit
 *
 * Text flow (no voice):
 *   1. Pre-configured messages or companion-app text → bridge
 *   2. Same streaming response path
 */

import {
  waitForEvenAppBridge,
  TextContainerProperty,
  CreateStartUpPageContainer,
  TextContainerUpgrade,
  OsEventTypeList,
} from '@evenrealities/even_hub_sdk'

// ═══════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════

/** WebSocket URL of the HermesGlass bridge server. */
const BRIDGE_URL = (import.meta.env.VITE_BRIDGE_URL as string) ||
  'wss://titagram.tail005130.ts.net:8448/ws'

/** ID for the single Hermes session this app uses. */
const SESSION_KEY = 'g2-hermes'

// ═══════════════════════════════════════════════════════════════════
// DISPLAY GEOMETRY — G2 is 576 x 288, 4-bit greyscale
// ═══════════════════════════════════════════════════════════════════

const DISPLAY_W = 576
const DISPLAY_H = 288

// Body container (main text area)
const BODY_W = DISPLAY_W
const BODY_H = 240
const BODY_PAD = 6

// Status bar (bottom strip)
const STATUS_W = DISPLAY_W
const STATUS_H = 28
const STATUS_Y = BODY_H + 4

// ═══════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════

type AppState = 'idle' | 'listening' | 'thinking' | 'streaming' | 'showing' | 'error'
let state: AppState = 'idle'

/** Full accumulated Hermes response. */
let responseText = ''

/** Current page index when response is paginated. */
let currentPage = 0

/** Paginated response pages. */
let pages: string[] = []

/** Connection status. */
let connected = false

/** Whether we're recording audio. */
let recording = false

/** The WebSocket connection to the bridge. */
// let bridgeWs: WebSocket | null = null  // unused, bridge client manages its own ws

// ═══════════════════════════════════════════════════════════════════
// BRIDGE WEBSOCKET CLIENT (simplified OpenClaw protocol)
// ═══════════════════════════════════════════════════════════════════

class HermesBridgeClient {
  private ws: WebSocket | null = null
  private url: string
  private msgId = 0
  private shouldClose = false
  private reconnectTimer: number | null = null
  private reconnectInterval = 1000
  private maxReconnectInterval = 30000

  // Event handlers
  onConnect: (() => void) | null = null
  onDisconnect: (() => void) | null = null
  onDelta: ((text: string) => void) | null = null
  onFinal: ((text: string) => void) | null = null
  onError: ((msg: string) => void) | null = null

  constructor(url: string) {
    this.url = url
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        resolve()
        return
      }

      this.shouldClose = false
      try {
        this.ws = new WebSocket(this.url)

        this.ws.onopen = () => {
          console.log('[HermesGlass] Bridge connected')
          this.reconnectInterval = 1000
          this.sendHandshake()
          this.onConnect?.()
          resolve()
        }

        this.ws.onmessage = (event) => {
          this.handleMessage(event.data as string)
        }

        this.ws.onerror = (err) => {
          console.error('[HermesGlass] WebSocket error:', err)
          this.onError?.('Connection error')
          reject(new Error('WebSocket error'))
        }

        this.ws.onclose = () => {
          console.log('[HermesGlass] Bridge disconnected')
          this.ws = null
          this.onDisconnect?.()
          if (!this.shouldClose) {
            this.scheduleReconnect()
          }
        }
      } catch (err) {
        reject(err)
      }
    })
  }

  disconnect() {
    this.shouldClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  private sendHandshake() {
    this.send({
      type: 'req',
      id: this.genId(),
      method: 'connect',
      params: {
        minProtocol: 3,
        maxProtocol: 3,
        client: {
          id: 'hermes-glass',
          version: '1.0.0',
          platform: 'web',
          mode: 'operator',
        },
        role: 'operator',
        scopes: ['operator.read', 'operator.write'],
        caps: [],
        commands: [],
        permissions: {},
        locale: 'en-US',
        userAgent: 'hermes-glass/1.0.0',
      },
    })
  }

  private handleMessage(data: string) {
    // The bridge sends newline-delimited JSON; split and process each.
    for (const line of data.split('\n')) {
      if (!line.trim()) continue
      try {
        const msg = JSON.parse(line)
        if (msg.type === 'res') {
          // Response to a request — we don't need to do anything special
          if (msg.ok && msg.payload?.type === 'hello-ok') {
            console.log('[HermesGlass] Handshake ok, protocol:', msg.payload.protocol)
          }
        } else if (msg.type === 'event') {
          if (msg.event === 'chat.event') {
            const payload = msg.payload
            if (payload.state === 'delta') {
              this.onDelta?.(payload.message?.content || '')
            } else if (payload.state === 'final') {
              this.onFinal?.(payload.message?.content || '')
            } else if (payload.state === 'error') {
              this.onError?.(payload.errorMessage || 'Unknown error')
            }
          } else if (msg.event === 'agent.completion') {
            const cp = msg.payload
            if (cp.status === 'error') {
              this.onError?.(cp.result || 'Task failed')
            }
          }
        }
      } catch (err) {
        console.error('[HermesGlass] Parse error:', err)
      }
    }
  }

  /** Send a chat message to Hermes via the bridge. */
  sendChat(message: string) {
    this.send({
      type: 'req',
      id: this.genId(),
      method: 'chat.send',
      params: {
        sessionKey: SESSION_KEY,
        message,
        idempotencyKey: `send_${Date.now()}`,
      },
    })
  }

  private send(obj: any) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('[HermesGlass] Cannot send: not connected')
      return
    }
    this.ws.send(JSON.stringify(obj))
  }

  private genId(): string {
    return `msg_${Date.now()}_${++this.msgId}`
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return
    console.log(`[HermesGlass] Reconnecting in ${this.reconnectInterval}ms...`)
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectInterval = Math.min(this.reconnectInterval * 1.5, this.maxReconnectInterval)
      this.connect().catch(() => {})
    }, this.reconnectInterval)
  }
}

// ═══════════════════════════════════════════════════════════════════
// TEXT UTILITIES
// ═══════════════════════════════════════════════════════════════════

/** Rough character estimate per page based on G2 display geometry. */
const CHARS_PER_PAGE = 220 // ~576x240 @ font size 18

/** Split long text into pages that fit on the G2 display. */
function paginate(text: string): string[] {
  if (text.length <= CHARS_PER_PAGE) return [text]

  const paragraphs = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
  const result: string[] = []
  let buffer = ''
  let bufferLen = 0

  for (const para of paragraphs) {
    const cost = para.length + (buffer ? 2 : 0) // +2 for blank line
    if (bufferLen + cost > CHARS_PER_PAGE && buffer) {
      result.push(buffer)
      buffer = para
      bufferLen = para.length
    } else {
      buffer = buffer ? `${buffer}\n\n${para}` : para
      bufferLen += cost
    }
  }
  if (buffer) result.push(buffer)

  // If we have a single very long paragraph, hard-split it
  const final: string[] = []
  for (const page of result) {
    if (page.length <= CHARS_PER_PAGE) {
      final.push(page)
    } else {
      for (let i = 0; i < page.length; i += CHARS_PER_PAGE) {
        final.push(page.slice(i, i + CHARS_PER_PAGE))
      }
    }
  }
  return final
}

/** Clean text for G2 display: strip markdown, limit length. */
function cleanForG2(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '[code]')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/https?:\/\/\S+/gi, '[link]')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .trim()
}

// ═══════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════

async function main() {
  console.log('[HermesGlass] Starting...')

  // ── 1. Initialize Even Hub bridge ──
  const bridge = await waitForEvenAppBridge()
  console.log('[HermesGlass] Even Hub bridge ready')

  // ── 2. Create display containers ──
  const body = new TextContainerProperty({
    xPosition: 0,
    yPosition: 0,
    width: BODY_W,
    height: BODY_H,
    borderWidth: 0,
    borderColor: 5,
    paddingLength: BODY_PAD,
    containerID: 1,
    containerName: 'body',
    content: 'HermesGlass\n\nConnecting to Hermes...',
    isEventCapture: 1,
  })

  const status = new TextContainerProperty({
    xPosition: 0,
    yPosition: STATUS_Y,
    width: STATUS_W,
    height: STATUS_H,
    borderWidth: 0,
    borderColor: 5,
    paddingLength: 4,
    containerID: 2,
    containerName: 'status',
    content: 'Status: connecting',
    isEventCapture: 0,
  })

  const created = await bridge.createStartUpPageContainer(
    new CreateStartUpPageContainer({
      containerTotalNum: 2,
      textObject: [body, status],
    }),
  )
  if (created !== 0) {
    console.error('[HermesGlass] Failed to create page container:', created)
    return
  }
  console.log('[HermesGlass] Display containers created')

  // ── 3. Initialize Hermes bridge WebSocket ──
  const bridgeClient = new HermesBridgeClient(BRIDGE_URL)

  // Debounced render to avoid flooding the BLE queue
  let renderTimer: number | null = null

  async function updateBody(content: string) {
    if (renderTimer !== null) return
    renderTimer = window.setTimeout(async () => {
      renderTimer = null
      await bridge.textContainerUpgrade(
        new TextContainerUpgrade({
          containerID: 1,
          containerName: 'body',
          content,
        }),
      )
    }, 120)
  }

  async function updateStatus(content: string) {
    await bridge.textContainerUpgrade(
      new TextContainerUpgrade({
        containerID: 2,
        containerName: 'status',
        content,
      }),
    )
  }

  function setState(newState: AppState) {
    state = newState
    const statusText = {
      idle: 'Status: idle | tap: talk | double-tap: exit',
      listening: 'Status: LISTENING | double-tap: cancel',
      thinking: 'Status: thinking...',
      streaming: 'Status: streaming | tap: page',
      showing: 'Status: tap: next page | double-tap: exit',
      error: 'Status: error | tap: retry | double-tap: exit',
    }[newState]
    updateStatus(statusText)
  }

  // ── 4. Bridge WebSocket event handlers ──
  bridgeClient.onConnect = async () => {
    connected = true
    setState('idle')
    await updateBody('HermesGlass\n\nConnected to Hermes.\n\nLong-press right temple to talk.\n\nDouble-tap to exit.')
    console.log('[HermesGlass] Connected, state=idle')
  }

  bridgeClient.onDisconnect = async () => {
    connected = false
    setState('error')
    await updateBody('HermesGlass\n\nDisconnected from Hermes.\n\nReconnecting...')
  }

  bridgeClient.onDelta = async (text: string) => {
    if (state !== 'streaming' && state !== 'thinking') setState('streaming')
    // Show accumulated text as it arrives
    const clean = cleanForG2(text)
    pages = paginate(clean)
    currentPage = 0
    await updateBody(pages[currentPage] || clean)
  }

  bridgeClient.onFinal = async (text: string) => {
    const clean = cleanForG2(text)
    responseText = clean
    pages = paginate(clean)
    currentPage = 0
    await updateBody(pages[0] || '(no response)')
    if (pages.length > 1) {
      setState('showing')
    } else {
      setState('idle')
      await updateStatus(`Status: idle | tap: talk | double-tap: exit`)
    }
    console.log('[HermesGlass] Final response:', clean.length, 'chars,', pages.length, 'pages')
  }

  bridgeClient.onError = async (msg: string) => {
    setState('error')
    await updateBody(`HermesGlass\n\nError: ${msg}`)
  }

  // ── 5. Connect to bridge ──
  bridgeClient.connect().catch((err: Error) => {
    console.error('[HermesGlass] Initial connection failed:', err)
  })

  // ── 6. Voice recording (uses glasses mic) ──
  // PCM audio buffer
  let pcmChunks: ArrayBuffer[] = []

  async function startRecording() {
    if (recording) return
    recording = true
    pcmChunks = []
    setState('listening')
    await updateBody('HermesGlass\n\nListening...\n\nSpeak now, double-tap to cancel.')
    await bridge.audioControl(true)
    console.log('[HermesGlass] Mic activated')
  }

  async function stopRecording() {
    if (!recording) return
    recording = false
    await bridge.audioControl(false)
    console.log('[HermesGlass] Mic stopped, chunks:', pcmChunks.length)

    if (pcmChunks.length === 0) {
      setState('idle')
      await updateBody('HermesGlass\n\nNo audio captured.\n\nLong-press right temple to talk.')
      return
    }

    // For now, we don't have a browser STT pipeline in this v1.
    // The companion app's default voice input path is used instead.
    // The audio chunks are available for a future STT integration.
    // See README for how to add whisper.cpp WASM or cloud STT.
    setState('thinking')
    await updateBody('HermesGlass\n\nProcessing voice input...\n\n(Add STT provider to enable)')

    // TODO: Integrate STT here:
    //   1. Convert PCM chunks to a single ArrayBuffer
    //   2. Send to STT provider (whisper.cpp WASM, Deepgram, AssemblyAI, etc.)
    //   3. Get transcript text
    //   4. bridgeClient.sendChat(transcript)
  }

  // ── 7. Manual text input (for testing without voice) ──
  // When the companion app sends a message via the bridge WebSocket,
  // it arrives as a chat.send request.  For now, we support tap-triggered
  // preset queries for demo purposes.

  const DEMO_QUESTIONS = [
    'What time is it?',
    'What is the weather like?',
    'Tell me a fun fact.',
    'What can you do?',
    'What is my system status?',
  ]
  let demoIdx = 0

  async function sendDemoQuery() {
    if (!connected) {
      await updateBody('HermesGlass\n\nNot connected to Hermes yet. Wait...')
      return
    }
    const question = DEMO_QUESTIONS[demoIdx % DEMO_QUESTIONS.length]
    demoIdx++
    setState('thinking')
    await updateBody(`HermesGlass\n\nQ: ${question}\n\nWaiting for Hermes...`)
    bridgeClient.sendChat(question)
  }

  // ── 8. Event handling (tap, double-tap, scroll) ──
  // Protobuf omits zero-value fields, so CLICK_EVENT (0) arrives as undefined.
  // Always coalesce with ?? 0 before comparing.
  let cleanedUp = false
  function cleanup() {
    if (cleanedUp) return
    cleanedUp = true
    bridge.audioControl(false)
    bridgeClient.disconnect()
    unsubscribe()
  }

  const unsubscribe = bridge.onEvenHubEvent(async (event: any) => {
    const sysType = event.sysEvent?.eventType ?? null
    const textType = event.textEvent?.eventType ?? null

    // Double-tap → exit (always works, no matter which envelope)
    if (sysType === OsEventTypeList.DOUBLE_CLICK_EVENT || textType === OsEventTypeList.DOUBLE_CLICK_EVENT) {
      bridge.shutDownPageContainer(1)
      return
    }

    // Audio PCM frames — collect for STT
    const pcm = event.audioEvent?.audioPcm
    if (pcm && recording) {
      if (pcm instanceof ArrayBuffer) {
        pcmChunks.push(pcm)
      } else if (pcm instanceof Uint8Array) {
        pcmChunks.push(pcm.buffer as ArrayBuffer)
      }
      return
    }

    // Single tap → context-dependent action
    if (sysType === OsEventTypeList.CLICK_EVENT || textType === OsEventTypeList.SCROLL_BOTTOM_EVENT) {
      switch (state) {
        case 'idle':
          // Tap in idle → start recording
          await startRecording()
          break
        case 'listening':
          // Tap while listening → stop and send
          await stopRecording()
          break
        case 'showing':
          // Tap while showing → next page
          if (currentPage < pages.length - 1) {
            currentPage++
            await updateBody(pages[currentPage])
            await updateStatus(`Page ${currentPage + 1}/${pages.length} | tap: next | double-tap: exit`)
          } else {
            // Last page → back to idle
            setState('idle')
            await updateBody('HermesGlass\n\nEnd of response.\n\nLong-press right temple to talk.')
          }
          break
        case 'error':
          // Tap on error → retry connection
          bridgeClient.connect().catch(() => {})
          break
        case 'thinking':
        case 'streaming':
          // Tap during thinking/streaming → no-op (or could interrupt)
          break
      }
      return
    }

    // Scroll up → previous page
    if (textType === OsEventTypeList.SCROLL_TOP_EVENT) {
      if (state === 'showing' && currentPage > 0) {
        currentPage--
        await updateBody(pages[currentPage])
        await updateStatus(`Page ${currentPage + 1}/${pages.length} | tap: next | double-tap: exit`)
      }
      return
    }

    // System exit
    if (sysType === OsEventTypeList.SYSTEM_EXIT_EVENT || sysType === OsEventTypeList.ABNORMAL_EXIT_EVENT) {
      cleanup()
    }
  })

  // Handle beforeunload for dev mode
  window.addEventListener('beforeunload', cleanup)

  console.log('[HermesGlass] App initialized, waiting for events')
}

// Run the app
main().catch((err) => {
  console.error('[HermesGlass] Fatal error:', err)
})