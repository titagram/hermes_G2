# HermesGlass — Even Realities G2 → Hermes Agent

A server-driven channel that lets Even Realities G2 smart glasses interact with Hermes Agent through voice, shortcuts, dashboard data, and alerts.

```
G2 Glasses → HermesGlass App → HermesGlass Bridge → Hermes Agent
     ↑               │              │                 │
     └── UI surface ←┴── actions ←──┴── semantic data ←┘
```

## Architecture

```
hermes-g2-bridge/
├── src/
│   ├── __init__.py
│   ├── bridge_server.py      # WebSocket server (OpenClaw protocol → Hermes API)
│   ├── g2_approval.py        # G2 approval queue and bounded session grants
│   ├── g2_hexstrike.py       # Bounded direct HexStrike worker for G2 recon
│   ├── g2_jobs.py            # Durable in-process G2 job manager
│   ├── g2_state.py           # SQLite-backed G2 sessions/events/jobs store
│   └── g2_surface.py         # Semantic G2 surface/actions model
├── app/                      # Even Hub app (Vite + TypeScript + Even Hub SDK)
│   ├── app.json              # Even Hub manifest
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── .env.example
│   └── src/
│       ├── main.ts           # G2 app: profiles, surface UI, voice capture, pagination
│       ├── config.ts         # App config and connection profiles
│       ├── surface.ts        # Semantic surface normalization/render helpers
│       ├── audio.ts          # PCM → WAV helpers
│       ├── events.ts         # G2/ring/list event normalization
│       ├── styles.css        # Phone-side configuration UI
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
   - Exposes G2 channel extensions: `g2.surface.get`, `g2.surface.refresh`, `g2.action.run`, `g2.target.*`, `g2.approval.*`, `g2.bootstrap.status`
   - Persists G2 session state in SQLite, including targets, pending approvals, grants, recent events and HexStrike job status
   - Owns long-running G2 jobs outside the WebSocket connection, so a reconnect can resume status/report visibility
   - Runs on your machine, listens on port 18790 (the OpenClaw default)

2. **Even Hub App** (`app/`)
   - A Vite + TypeScript web app that runs inside the Even companion app's WebView
   - Uses the official `@evenrealities/even_hub_sdk` to render a server-driven home surface on the G2 display
   - Stores multiple Hermes connection profiles locally on the phone
   - Persists a stable client session id and the last seen bridge event id for reconnect/replay
   - Captures microphone audio via `bridge.audioControl(true)`
   - Sends captured WAV audio to the bridge for Hermes STT, then sends the transcript to Hermes chat
   - Connects to the bridge server via WebSocket and streams responses to the glasses display
   - Native list home, detail pagination, action confirmation, tap navigation, double-tap back/exit

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
npx evenhub pack app.json dist -o HermesGlass.ehpk
# Upload the .ehpk file through the Even Hub dev portal
```

## How to Use

| Action | Effect |
|--------|--------|
| **Scroll home list** | Move through server-provided actions/data |
| **Press home item** | Open data detail, run action, or start voice |
| **Press VOICE** | Start voice recording |
| **Tap ring or temple (listening)** | Stop recording, transcribe, and send to Hermes |
| **Press/scroll detail** | Next/previous page |
| **Double-tap on detail/confirm/result** | Back to home |
| **Double-tap on home/config** | Exit app |

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
| `HERMES_STT_MODEL` | `whisper-1` | STT model for `/v1/audio/transcriptions` |
| `HERMES_STT_PROVIDER` | `auto` | `auto`, `hermes`, or `local` |
| `HERMES_LOCAL_STT_MODEL` | `tiny` | faster-whisper model used by the local STT provider |
| `HERMES_LOCAL_STT_DEVICE` | `cpu` | faster-whisper device, for example `cpu` or `cuda` |
| `HERMES_LOCAL_STT_COMPUTE_TYPE` | `int8` | faster-whisper compute type |
| `HERMES_LOCAL_STT_LANGUAGE` | (auto) | Optional language code such as `it` or `en` |
| `HERMES_G2_STATE_DB` | `~/.hermes-g2/state.sqlite3` | SQLite database for G2 session recovery |
| `G2_HEXSTRIKE_PROJECT_DIR` | `/home/titagram/hexstrike-kali-hermes` | HexStrike/Kali helper project directory |
| `G2_HEXSTRIKE_SCRIPT` | `<project>/run-lan-scan.sh` | Bounded scan wrapper used by the G2 `RECON` action |
| `G2_HEXSTRIKE_REPORT_BASE_URL` | `https://titagram.tail005130.ts.net:8899` | Report base URL shown on G2 |
| `G2_HEXSTRIKE_ALLOWED_CIDRS` | `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | Comma-separated target ranges allowed for direct G2 recon |
| `G2_HEXSTRIKE_PROFILE` | `quick` | Scan wrapper profile, usually `quick` |
| `G2_HEXSTRIKE_EXTRA_NMAP` | `--host-timeout 60s --max-retries 2` | Extra bounded nmap args passed to the wrapper |
| `LOG_LEVEL` | `INFO` | Logging level |

### Even Hub App

The app opens with a mobile Even Hub configuration screen. Set these values
there and tap **Save & Connect**:

- Bridge WebSocket URL, for example `wss://titagram.tail005130.ts.net:8448/ws`
- Optional token
- Multiple connection profiles for multiple Hermes instances
- HexStrike target and scope for approved HTB/security workflows
- STT model, default `whisper-1`
- Recording timeout
- Input source: ring and temples, ring only, or temples only

`app/.env.local` is optional and only sets the build-time default URL:

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

Glasses → Bridge:  {type: "req", method: "audio.transcribe", params: {audioBase64: "...", mimeType: "audio/wav"}}
Bridge → Glasses:  {type: "res", ok: true, payload: {text: "..."}}

Glasses → Bridge:  {type: "req", method: "g2.surface.get", params: {}}
Bridge → Glasses:  {type: "res", ok: true, payload: {version: 1, status: {...}, items: [...]}}

Glasses → Bridge:  {type: "req", method: "g2.session.resume", params: {clientSessionId: "g2s-...", profileId: "default", lastSeenEventId: 42}}
Bridge → Glasses:  {type: "res", ok: true, payload: {session: {...}, pendingApprovals: [...], jobs: [...], missedEvents: [...]}}

Glasses → Bridge:  {type: "req", method: "g2.action.run", params: {id: "mail"}}
Bridge → Glasses:  {type: "res", ok: true, payload: {accepted: true, state: "running"}}

Glasses → Bridge:  {type: "req", method: "g2.target.set", params: {target: "10.129.22.74", scope: "HTB authorized machine"}}
Bridge → Glasses:  {type: "res", ok: true, payload: {target: "10.129.22.74", scope: "HTB authorized machine"}}

Glasses → Bridge:  {type: "req", method: "g2.approval.respond", params: {id: "appr_123", optionId: "session-low"}}
Bridge → Glasses:  {type: "res", ok: true, payload: {accepted: true, state: "running"}}

Glasses → Bridge:  {type: "req", method: "g2.bootstrap.status", params: {}}
Bridge → Glasses:  {type: "res", ok: true, payload: {plugin: "hermes-g2", installed: false, ...}}

Bridge → Glasses:  {type: "event", event: "chat.event", payload: {eventId: 43, state: "delta", message: {...}}}
Bridge → Glasses:  {type: "event", event: "chat.event", payload: {eventId: 44, state: "final", message: {...}}}
Bridge → Glasses:  {type: "event", event: "agent.completion", payload: {eventId: 45, status: "ok", result: "..."}}
```

The bridge translates normal chat and voice turns to Hermes API Server calls:

```
Bridge → Hermes:  POST /v1/chat/completions  {model: "hermes-agent", messages: [...], stream: true}
Hermes → Bridge:  SSE data: {choices: [{delta: {content: "..."}}]}
                  data: [DONE]
```

The G2 `RECON` action is intentionally narrower. After G2 approval, the
bridge runs the bounded HexStrike wrapper directly and streams status lines
back as `chat.event` updates. This avoids sending a broad prompt to Hermes
that can trigger invisible Hermes-side tool approvals or long-running agent
loops before the glasses receive feedback.

### G2 Surface Contract

The server sends semantic actions/data only; the G2 app owns exact layout and pagination.

```json
{
  "version": 1,
  "status": { "agent": "idle", "connection": "ok" },
  "items": [
    { "id": "server", "type": "data", "label": "SERVER", "summary": "LOAD 0.20 RAM 12%" },
    { "id": "job:job_123", "type": "data", "label": "JOB", "summary": "RECON running 10.129.22.74" },
    { "id": "mail", "type": "action", "label": "MAIL", "summary": "important unread", "action": { "confirm": false, "risk": "read_only" } },
    { "id": "voice", "type": "voice", "label": "VOICE", "summary": "press to talk" }
  ]
}
```

The G2 app sends only action ids back to the bridge. Prompts remain server-side.

### HexStrike Approval Workflow

If the HexStrike/Kali helper project is installed on the bridge host, the
bridge can expose a controlled `RECON` action. The mobile Even Hub
configuration screen supplies the current target and scope. The glasses never
need to type the target directly.

When `RECON` is selected, the bridge normalizes and validates the target
against `G2_HEXSTRIKE_ALLOWED_CIDRS`, then creates a structured approval
request instead of immediately launching the workflow. The G2 display shows
configurable options supplied by the bridge:

- `ONCE`: approve only this operation.
- `SESSION LOW`: approve similar low-risk operations for the same target and
  workflow for a short TTL.
- `SESSION MED`: approve similar medium-risk operations for the same target and
  workflow for a shorter TTL.
- `DENY`: deny the operation.
- `DETAIL`: inspect the reason, target, scope and risk without resolving the
  approval.

Session approvals are bounded by target, workflow, risk ceiling and TTL. If
HexStrike needs a higher-risk operation, a different workflow, or a different
target, the bridge must ask again.

Approved HexStrike scans are tracked as durable G2 jobs. If the glasses or
mobile WebView reconnect during a scan, `g2.session.resume` restores active
jobs, pending approvals, active grants and missed events. The home surface then
shows a `JOB` data row with state, target, recent log output and report URL.

Targets such as `192.168.1.0 /24` or `192.168.1.0 \24` are normalized to
`192.168.1.0/24`. Public ranges are rejected by default; for example
`192.169.1.0/24` will not run unless explicitly added to
`G2_HEXSTRIKE_ALLOWED_CIDRS`.

## Adding STT (Speech-to-Text)

The app captures PCM audio from the glasses microphone (16kHz, mono, s16le),
wraps it as WAV, and sends it over the existing OpenClaw WebSocket with
`audio.transcribe`. The bridge can transcribe it in two ways:

- `HERMES_STT_PROVIDER=hermes`: forward the WAV file to Hermes at
  `POST /v1/audio/transcriptions`.
- `HERMES_STT_PROVIDER=local`: transcribe on the bridge machine with
  `faster-whisper`.
- `HERMES_STT_PROVIDER=auto`: try Hermes first, then switch to local STT if
  Hermes returns 404 for the STT endpoint.

For Hermes versions that expose chat but not `/v1/audio/transcriptions`, use
`HERMES_STT_PROVIDER=local`. Start with `HERMES_LOCAL_STT_MODEL=tiny` for low
latency; use `base` if accuracy matters more than speed.

## Troubleshooting

### Bridge server won't start
- Check port 18790 is not in use: `ss -tlnp | grep 18790`
- Check Hermes API is running: `curl http://127.0.0.1:8642/health`
- Check logs: `journalctl --user -u hermes-glass-bridge -f`

### Glasses can't connect
- Verify Tailscale serve: `tailscale serve status`
- Check the bridge URL in the app's mobile configuration screen
- Test the WebSocket manually:
  `python3 test_bridge.py wss://your-host:8448/ws --no-chat --surface --run-action server`

The protocol probe should print `Capabilities: audioTranscribe=True` and
`g2Surface=True`. If it instead reports a payload like `{"ok": true}`,
the process behind the URL is still the old bridge and must be restarted or
redeployed.

### No response from Hermes
- Check API_SERVER_KEY is set in `~/.hermes/.env`
- Test the API directly: `curl -H "Authorization: Bearer YOUR_KEY" http://127.0.0.1:8642/v1/chat/completions -d '{"model":"hermes-agent","messages":[{"role":"user","content":"hi"}]}'`

## License

MIT
