#!/usr/bin/env python3
"""
HermesGlass Bridge Server
=========================
WebSocket server that speaks the OpenClaw gateway protocol on the wire
and translates every request to the Hermes Agent API Server
(OpenAI-compatible, /v1/chat/completions with SSE streaming).

The G2 glasses app connects with wss://<this-server> and thinks it is
talking to an OpenClaw gateway.

Uses the `websockets` library for the WS server (native, reliable) and
`aiohttp` for the HTTP client to the Hermes API Server.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import time
import uuid
from typing import Any, Dict, Optional, Set

try:
    import websockets
    from websockets.asyncio.server import serve
except ImportError:
    raise SystemExit("websockets is required: pip install websockets")

try:
    import aiohttp
except ImportError:
    raise SystemExit("aiohttp is required: pip install aiohttp")

logger = logging.getLogger("hermes-glass")

# ─── defaults ────────────────────────────────────────────────────
DEFAULT_WS_HOST = "0.0.0.0"
DEFAULT_WS_PORT = 18790
DEFAULT_HERMES_URL = "http://127.0.0.1:8642"
PROTOCOL_VERSION = 3
DELTA_THRESHOLD = 40  # chars before a delta flush

# ─── protocol helpers ────────────────────────────────────────────

def make_response(msg_id: str, payload: dict) -> str:
    return json.dumps({"type": "res", "id": msg_id, "ok": True, "payload": payload})

def make_error(msg_id: str, code: int, message: str) -> str:
    return json.dumps({"type": "res", "id": msg_id, "ok": False, "error": {"code": code, "message": message}})

def make_event(event: str, payload: dict) -> str:
    return json.dumps({"type": "event", "event": event, "payload": payload})

def make_hello_ok(msg_id: str) -> str:
    return make_response(msg_id, {
        "type": "hello-ok",
        "protocol": PROTOCOL_VERSION,
        "server": "hermes-glass/1.0",
        "capabilities": {"streaming": True, "sessions": True},
    })

# ─── Hermes API client ───────────────────────────────────────────

class HermesClient:
    """Thin async client for the Hermes API Server (OpenAI-compatible)."""

    def __init__(self, base_url: str, api_key: str, model: str = "hermes-agent"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120, connect=10),
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._session

    async def chat_stream(self, message: str, session_id: Optional[str] = None):
        """POST /v1/chat/completions with stream=True. Yields (delta, final, finish_reason)."""
        session = await self._get_session()
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": message}],
            "stream": True,
        }
        full_text = ""
        url = f"{self.base_url}/v1/chat/completions"
        try:
            async with session.post(url, json=body, headers=headers) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logger.error("Hermes API %d: %s", resp.status, err[:300])
                    yield (None, f"[Hermes API error {resp.status}]", None)
                    return
                async for line in resp.content:
                    line = line.decode("utf-8", errors="replace")
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        full_text += delta["content"]
                        yield (delta["content"], None, None)
                    if choice.get("finish_reason"):
                        yield (None, full_text, choice["finish_reason"])
        except aiohttp.ClientError as exc:
            logger.error("Hermes API error: %s", exc)
            yield (None, f"[Connection error: {exc}]", None)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

# ─── WebSocket connection handler ───────────────────────────────

class BridgeConnection:
    """One client WebSocket connection."""

    def __init__(self, ws, hermes: HermesClient, conn_id: str):
        self.ws = ws
        self.hermes = hermes
        self.conn_id = conn_id
        self.session_id: Optional[str] = None
        self.agent_id = "hermes-main"
        self.subscribed: Set[str] = set()

    async def handle(self):
        """Main read loop for aiohttp WebSocketResponse."""
        logger.info("Connection %s opened", self.conn_id)
        try:
            from aiohttp import web as _web
            async for msg in self.ws:
                if msg.type == _web.WSMsgType.TEXT:
                    raw = msg.data
                elif msg.type == _web.WSMsgType.BINARY:
                    raw = msg.data.decode("utf-8", errors="replace")
                elif msg.type in (_web.WSMsgType.CLOSE, _web.WSMsgType.CLOSING, _web.WSMsgType.CLOSED):
                    break
                else:
                    continue
                raw = raw.strip()
                if not raw:
                    continue
                for line in raw.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    await self._process_line(line)
        except Exception as exc:
            logger.info("Connection %s ended: %s", self.conn_id, exc)
        logger.info("Connection %s closed", self.conn_id)

    async def _process_line(self, line: str):
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Bad JSON from %s: %s", self.conn_id, line[:200])
            return

        msg_type = msg.get("type")
        msg_id = msg.get("id", "")

        if msg_type == "req":
            await self._handle_request(msg, msg_id)
        elif msg_type == "event":
            logger.debug("Client event: %s", msg.get("event"))
        else:
            logger.debug("Unknown type %s", msg_type)

    async def _handle_request(self, msg: dict, msg_id: str):
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "connect":
            await self.ws.send_str(make_hello_ok(msg_id))
            logger.info("Handshake ok for %s (protocol %d)", self.conn_id, PROTOCOL_VERSION)
            return

        if method == "chat.send":
            text = params.get("message", "")
            session_key = params.get("sessionKey", self.agent_id)
            await self.ws.send_str(make_response(msg_id, {"accepted": True}))
            asyncio.create_task(self._handle_chat(session_key, text))
            return

        if method == "chat.subscribe":
            self.subscribed.add(params.get("sessionKey", ""))
            await self.ws.send_str(make_response(msg_id, {"subscribed": True}))
            return

        if method == "chat.history":
            await self.ws.send_str(make_response(msg_id, {"messages": []}))
            return

        if method == "chat.unsubscribe":
            self.subscribed.discard(params.get("sessionKey", ""))
            await self.ws.send_str(make_response(msg_id, {"unsubscribed": True}))
            return

        # Generic ack
        await self.ws.send_str(make_response(msg_id, {"ok": True}))

    async def _handle_chat(self, session_key: str, text: str):
        """Stream a chat turn, emitting OpenClaw-format events."""
        run_id = str(uuid.uuid4())
        ts = int(time.time() * 1000)

        # Agent busy
        await self.ws.send_str(make_event("agent.event", {
            "runId": run_id, "seq": 0, "stream": self.agent_id,
            "ts": ts, "data": {"sessionKey": session_key, "status": "busy"},
        }))

        accumulated = ""
        seq = 0
        last_flush = 0
        finish_reason = None

        async for delta, final, fr in self.hermes.chat_stream(text, session_id=self.session_id):
            if delta is not None:
                accumulated += delta
                if len(accumulated) - last_flush >= DELTA_THRESHOLD:
                    seq += 1
                    await self.ws.send_str(make_event("chat.event", {
                        "runId": run_id, "sessionKey": session_key,
                        "seq": seq, "state": "delta",
                        "message": {"role": "assistant", "content": accumulated},
                    }))
                    last_flush = len(accumulated)
            if final is not None:
                accumulated = final if final else accumulated
                finish_reason = fr

        if not accumulated:
            accumulated = "(no response)"

        seq += 1
        await self.ws.send_str(make_event("chat.event", {
            "runId": run_id, "sessionKey": session_key,
            "seq": seq, "state": "final",
            "message": {"role": "assistant", "content": accumulated},
            "stopReason": finish_reason or "stop",
        }))

        # Completion + idle
        await self.ws.send_str(make_event("agent.event", {
            "runId": run_id, "seq": seq + 1, "stream": self.agent_id,
            "ts": int(time.time() * 1000),
            "data": {"sessionKey": session_key, "status": "idle"},
        }))
        await self.ws.send_str(make_event("agent.completion", {
            "agentId": self.agent_id, "sessionKey": session_key,
            "runId": run_id, "status": "ok",
            "result": accumulated, "timestamp": int(time.time() * 1000),
        }))
        logger.info("Chat done %s (run %s, %d chars)", self.conn_id, run_id[:8], len(accumulated))

# ─── Unified aiohttp server (HTTP + WebSocket on same port) ─────
# This is critical for Tailscale serve: it does HTTPS->HTTP reverse proxy
# and needs the backend to handle both HTTP GET (health) and WS upgrade
# on the same port.

from aiohttp import web

async def http_health(request: web.Request) -> web.Response:
    hermes: HermesClient = request.app["hermes_client"]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(f"{hermes.base_url}/health") as r:
                hermes_ok = r.status == 200
                hermes_status = await r.json() if hermes_ok else {}
    except Exception:
        hermes_ok = False
        hermes_status = {}
    return web.json_response({
        "status": "ok", "bridge": "hermes-glass/1.0",
        "hermes_api": hermes_ok,
        "hermes_version": hermes_status.get("version", "?"),
        "hermes_platform": hermes_status.get("platform", "?"),
    })

async def http_root(request: web.Request) -> web.Response:
    return web.json_response({
        "name": "HermesGlass Bridge",
        "version": "1.0.0",
        "description": "WebSocket bridge from Even Realities G2 glasses to Hermes Agent",
        "endpoints": {
            "websocket": "/ws  (OpenClaw protocol)",
            "health": "/health",
        },
        "protocol": f"openclaw-v{PROTOCOL_VERSION}",
    })

async def ws_handler(request: web.Request) -> web.StreamResponse:
    """Handle a WebSocket upgrade from the glasses (or test client)."""
    hermes: HermesClient = request.app["hermes_client"]
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=2**20)
    await ws.prepare(request)

    conn_id = str(uuid.uuid4())[:8]
    conn = BridgeConnection(ws, hermes, conn_id)
    await conn.handle()
    return ws

def create_app(hermes_url: str, hermes_key: str, hermes_model: str) -> web.Application:
    app = web.Application()
    app["hermes_client"] = HermesClient(hermes_url, hermes_key, hermes_model)
    app.router.add_get("/", http_root)
    app.router.add_get("/health", http_health)
    app.router.add_get("/ws", ws_handler)
    return app

# ─── main ────────────────────────────────────────────────────────

async def main_async(args):
    from aiohttp import web
    app = create_app(args.hermes_url, args.hermes_key, args.hermes_model)

    # Also keep the old health on port+1 for backwards compat
    health_port = args.port + 1
    old_app = web.Application()
    old_app["hermes_client"] = app["hermes_client"]
    old_app.router.add_get("/health", http_health)
    runner = web.AppRunner(old_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", health_port)
    await site.start()
    logger.info("Legacy health on http://0.0.0.0:%d/health", health_port)

    logger.info("HermesGlass Bridge on %s:%d (WS+HTTP)", args.host, args.port)
    logger.info("Hermes API: %s (model: %s)", args.hermes_url, args.hermes_model)

    runner2 = web.AppRunner(app)
    await runner2.setup()
    site2 = web.TCPSite(runner2, args.host, args.port)
    await site2.start()
    await asyncio.Future()  # run forever

def main():
    parser = argparse.ArgumentParser(description="HermesGlass Bridge — G2 → Hermes")
    parser.add_argument("--host", default=os.getenv("BRIDGE_HOST", DEFAULT_WS_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("BRIDGE_PORT", DEFAULT_WS_PORT)))
    parser.add_argument("--hermes-url", default=os.getenv("HERMES_URL", DEFAULT_HERMES_URL))
    parser.add_argument("--hermes-key", default=os.getenv("API_SERVER_KEY", ""))
    parser.add_argument("--hermes-model", default=os.getenv("HERMES_MODEL", "hermes-agent"))
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not args.hermes_key:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("API_SERVER_KEY="):
                        args.hermes_key = line.strip().split("=", 1)[1]
                        break
    if not args.hermes_key:
        logger.warning("No API_SERVER_KEY — Hermes API calls will fail!")

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("Shutting down")

if __name__ == "__main__":
    main()