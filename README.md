# HermesGlass — Even Realities G2 → Hermes Agent

A complete bridge that lets you talk to your Hermes AI agent through Even Realities G2 smart glasses.

```
G2 Glasses (voice) → HermesGlass Bridge (WebSocket) → Hermes API Server → LLM
       ↑                                                                       |
       └──────────── text response streamed to glasses display ←──────────────┘
```

## Architecture

```
hermes-g2-bridge/
├── src/
│   ├── __init__.py
│   └── bridge_server.py      # WebSocket server (OpenClaw protocol → Hermes API)
├── app/                      # Even Hub app (Vite + TypeScript + Even Hub SDK)
│   ├── app.json              # Even Hub manifest
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── .env.example
│   └── src/
│       ├── main.ts           # Full G2 app: voice capture, streaming display, pagination
│       └── vite-env.d.ts
├── deploy/
│   └── hermes-glass-bridge.service   # systemd unit
├── requirements.txt
└── README.md
```

### Components

1. **Bridge Server** (`src/bridge_server.py`)
   - WebSocket server that speaks the OpenClaw gateway protocol (the protocol the G2 glasses app expects)
   - Translates every `chat.send` into a `POST /v1/chat/completions` call to the Hermes API Server
   - Streams the SSE response back as OpenClaw-format `chat.event` frames (delta → final)
   - Runs on your machine, listens on port 18790 (the OpenClaw default)

2. **Even Hub App** (`app/`)
   - A Vite + TypeScript web app that runs inside the Even companion app's WebView
   - Uses the official `@evenrealities/even_hub_sdk` to render text on the G2 display
   - Captures microphone audio via `bridge.audioControl(true)`
   - Connects to the bridge server via WebSocket and streams responses to the glasses display
   - Pagination, tap navigation, double-tap exit

## Prerequisites

- Even Realities G2 smart glasses paired with the Even Hub companion app
- Hermes Agent with API Server enabled (port 8642)
- Tailscale (for secure remote access)
- Python 3.11+ with `aiohttp` and `websockets`
- Node.js 18+ (for building the Even Hub app)

## Quick Start

### 1. Enable Hermes API Server

Make sure your Hermes API Server is running (already done if you followed the setup):
```bash
# Verify it's running
curl http://127.0.0.1:8642/health
```

### 2. Install bridge dependencies

```bash
cd ~/hermes-g2-bridge
pip install -r requirements.txt
```

### 3. Start the bridge server

```bash
# Foreground (for testing)
python3 -m src.bridge_server

# Or as a systemd service (recommended)
mkdir -p ~/.config/systemd/user
cp deploy/hermes-glass-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-glass-bridge
```

The bridge listens on `0.0.0.0:18790` by default and proxies to `http://127.0.0.1:8642`.

### 4. Expose the bridge on Tailscale

```bash
tailscale serve --bg --https 8448 http://127.0.0.1:18790
```

The bridge is now reachable at:
```
wss://<your-tailnet-name>:8448/ws
```

### 5. Build the Even Hub app

```bash
cd app
cp .env.example .env.local
# Edit .env.local if your bridge URL is different
npm install
npm run build
```

### 6. Deploy to glasses

**Option A: Dev mode (live reload)**
```bash
npm run dev
npx evenhub qr --url http://<your-ip>:5174
```
Scan the QR code with the Even Hub companion app.

**Option B: Pack and install**
```bash
npx evenhub pack
# Upload the .ehpk file through the Even Hub dev portal
```

## How to Use

| Action | Effect |
|--------|--------|
| **Long-press right temple** | Activate microphone (start voice input) |
| **Tap while listening** | Stop recording and send to Hermes |
| **Tap (idle)** | Start a new voice query |
| **Tap (showing)** | Next page of response |
| **Scroll up** | Previous page |
| **Double-tap** | Exit app |

## Configuration

### Bridge Server

Environment variables (or CLI flags):

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_HOST` | `0.0.0.0` | Bind address |
| `BRIDGE_PORT` | `18790` | WebSocket port |
| `HERMES_URL` | `http://127.0.0.1:8642` | Hermes API Server URL |
| `API_SERVER_KEY` | (from .env) | Hermes API authentication key |
| `HERMES_MODEL` | `hermes-agent` | Model name |
| `LOG_LEVEL` | `INFO` | Logging level |

### Even Hub App

Edit `app/.env.local`:

```
VITE_BRIDGE_URL=wss://your-tailnet-name:8448/ws
```

## Protocol

The bridge speaks the OpenClaw gateway WebSocket protocol:

```
Glasses → Bridge:  {type: "req", method: "connect", params: {minProtocol: 3, ...}}
Bridge → Glasses:  {type: "res", ok: true, payload: {type: "hello-ok", protocol: 3}}

Glasses → Bridge:  {type: "req", method: "chat.send", params: {message: "...", sessionKey: "..."}}
Bridge → Glasses:  {type: "res", ok: true, payload: {accepted: true}}

Bridge → Glasses:  {type: "event", event: "chat.event", payload: {state: "delta", message: {...}}}
Bridge → Glasses:  {type: "event", event: "chat.event", payload: {state: "final", message: {...}}}
Bridge → Glasses:  {type: "event", event: "agent.completion", payload: {status: "ok", result: "..."}}
```

The bridge translates this to Hermes API Server calls:

```
Bridge → Hermes:  POST /v1/chat/completions  {model: "hermes-agent", messages: [...], stream: true}
Hermes → Bridge:  SSE data: {choices: [{delta: {content: "..."}}]}
                  data: [DONE]
```

## Adding STT (Speech-to-Text)

The app captures PCM audio from the glasses microphone (16kHz, mono, s16le).
To enable voice-to-text, integrate an STT provider in `app/src/main.ts`:

### Option 1: whisper.cpp WASM (local, free)
```bash
npm install @xenova/transformers
```
```typescript
// In stopRecording():
import { pipeline } from '@xenova/transformers'
const transcriber = await pipeline('automatic-speech-recognition', 'openai/whisper-base')
const audio = mergePCMChunks(pcmChunks)
const result = await transcriber(audio, { sampling_rate: 16000 })
bridgeClient.sendChat(result.text)
```

### Option 2: Cloud STT (Deepgram, AssemblyAI, etc.)
```typescript
// In stopRecording():
const audioBlob = new Blob(pcmChunks, { type: 'audio/pcm' })
const formData = new FormData()
formData.append('audio', audioBlob)
const res = await fetch('https://api.deepgram.com/v1/listen', {
  method: 'POST',
  headers: { Authorization: `Bearer ${DEEPGRAM_API_KEY}` },
  body: formData,
})
const data = await res.json()
const transcript = data.results?.channels?.[0]?.alternatives?.[0]?.transcript
if (transcript) bridgeClient.sendChat(transcript)
```

### Option 3: Hermes built-in STT
Hermes has built-in STT support (faster-whisper, Groq, OpenAI). You can send
the raw audio to a custom endpoint on your bridge that forwards it to Hermes.

## Troubleshooting

### Bridge server won't start
- Check port 18790 is not in use: `ss -tlnp | grep 18790`
- Check Hermes API is running: `curl http://127.0.0.1:8642/health`
- Check logs: `journalctl --user -u hermes-glass-bridge -f`

### Glasses can't connect
- Verify Tailscale serve: `tailscale serve status`
- Check the bridge URL in `.env.local` matches your Tailscale hostname
- Test the WebSocket manually: `wscat -c wss://your-host:8448/ws`

### No response from Hermes
- Check API_SERVER_KEY is set in `~/.hermes/.env`
- Test the API directly: `curl -H "Authorization: Bearer YOUR_KEY" http://127.0.0.1:8642/v1/chat/completions -d '{"model":"hermes-agent","messages":[{"role":"user","content":"hi"}]}'`

## License

MIT