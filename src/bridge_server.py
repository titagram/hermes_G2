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
import base64
import binascii
import json
import logging
import os
import signal
import tempfile
import threading
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

from .g2_approval import ApprovalManager, TargetContext
from .g2_surface import build_default_surface, find_surface_item, prompt_for_action

logger = logging.getLogger("hermes-glass")

# ─── defaults ────────────────────────────────────────────────────
DEFAULT_WS_HOST = "0.0.0.0"
DEFAULT_WS_PORT = 18790
DEFAULT_HERMES_URL = "http://127.0.0.1:8642"
DEFAULT_STT_PROVIDER = "auto"
DEFAULT_LOCAL_STT_MODEL = "tiny"
DEFAULT_LOCAL_STT_DEVICE = "cpu"
DEFAULT_LOCAL_STT_COMPUTE_TYPE = "int8"
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

class HermesSttError(RuntimeError):
    """Hermes returned an error from its OpenAI-compatible STT endpoint."""

    def __init__(self, status: int, body: str):
        super().__init__(f"Hermes STT API error {status}")
        self.status = status
        self.body = body


class HermesClient:
    """Thin async client for the Hermes API Server (OpenAI-compatible)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "hermes-agent",
        stt_model: str = "whisper-1",
        stt_provider: str = DEFAULT_STT_PROVIDER,
        local_stt_model: str = DEFAULT_LOCAL_STT_MODEL,
        local_stt_device: str = DEFAULT_LOCAL_STT_DEVICE,
        local_stt_compute_type: str = DEFAULT_LOCAL_STT_COMPUTE_TYPE,
        local_stt_language: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.stt_model = stt_model
        provider = stt_provider.strip().lower()
        if provider not in {"auto", "hermes", "local"}:
            raise ValueError("stt_provider must be one of: auto, hermes, local")
        self.stt_provider = provider
        self.local_stt_model = local_stt_model
        self.local_stt_device = local_stt_device
        self.local_stt_compute_type = local_stt_compute_type
        self.local_stt_language = local_stt_language or None
        self._session: Optional[aiohttp.ClientSession] = None
        self._hermes_stt_unavailable = False
        self._local_stt = None
        self._local_stt_lock = threading.Lock()

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

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "g2.wav",
        mime_type: str = "audio/wav",
        model: Optional[str] = None,
    ) -> str:
        """Transcribe a WAV file through Hermes STT or the local fallback provider."""
        if self.stt_provider in {"auto", "hermes"} and not self._hermes_stt_unavailable:
            try:
                return await self._transcribe_audio_hermes(audio_bytes, filename, mime_type, model)
            except HermesSttError as exc:
                logger.error("Hermes STT API %d: %s", exc.status, exc.body[:300])
                if self.stt_provider == "hermes" or exc.status != 404:
                    raise
                self._hermes_stt_unavailable = True
                logger.warning("Hermes STT endpoint returned 404; using local STT fallback")

        if self.stt_provider in {"auto", "local"}:
            return await self._transcribe_audio_local(audio_bytes)

        raise RuntimeError("No STT provider is available")

    async def _transcribe_audio_hermes(
        self,
        audio_bytes: bytes,
        filename: str,
        mime_type: str,
        model: Optional[str],
    ) -> str:
        """POST /v1/audio/transcriptions with a WAV file. Returns transcript text."""
        session = await self._get_session()
        form = aiohttp.FormData()
        form.add_field("model", model or self.stt_model)
        form.add_field("file", audio_bytes, filename=filename, content_type=mime_type)
        url = f"{self.base_url}/v1/audio/transcriptions"

        async with session.post(url, data=form) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise HermesSttError(resp.status, body)
            try:
                data = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Hermes STT returned invalid JSON") from exc
            text = data.get("text") or data.get("transcript") or data.get("result") or ""
            return str(text).strip()

    async def _transcribe_audio_local(self, audio_bytes: bytes) -> str:
        return await asyncio.to_thread(self._transcribe_audio_local_sync, audio_bytes)

    def _load_local_stt(self):
        with self._local_stt_lock:
            if self._local_stt is not None:
                return self._local_stt
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "Local STT requires faster-whisper. Install bridge requirements "
                    "or set HERMES_STT_PROVIDER=hermes."
                ) from exc

            logger.info(
                "Loading local STT model %s (device=%s, compute_type=%s)",
                self.local_stt_model,
                self.local_stt_device,
                self.local_stt_compute_type,
            )
            self._local_stt = WhisperModel(
                self.local_stt_model,
                device=self.local_stt_device,
                compute_type=self.local_stt_compute_type,
            )
            return self._local_stt

    def _transcribe_audio_local_sync(self, audio_bytes: bytes) -> str:
        model = self._load_local_stt()
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="hermes-g2-", suffix=".wav", delete=False) as fh:
                fh.write(audio_bytes)
                tmp_name = fh.name

            segments, info = model.transcribe(
                tmp_name,
                beam_size=1,
                vad_filter=True,
                language=self.local_stt_language,
            )
            parts = [segment.text.strip() for segment in segments if segment.text and segment.text.strip()]
            text = " ".join(parts).strip()
            logger.info(
                "Local STT transcribed %.2fs audio to %d chars",
                getattr(info, "duration", 0.0) or 0.0,
                len(text),
            )
            return text
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

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
        self.target = TargetContext()
        self.approvals = ApprovalManager()

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

        if method == "bridge.capabilities":
            await self.ws.send_str(make_response(msg_id, {
                "audioTranscribe": True,
                "bootstrap": True,
                "configVersion": 2,
                "defaultSttModel": self.hermes.stt_model,
                "g2Approvals": True,
                "g2Surface": True,
                "g2Targets": True,
                "sttProvider": self.hermes.stt_provider,
                "localSttModel": self.hermes.local_stt_model,
                "protocol": PROTOCOL_VERSION,
                "surfaceVersion": 2,
            }))
            return

        if method in {"g2.surface.get", "g2.surface.refresh"}:
            await self.ws.send_str(make_response(msg_id, self._build_surface()))
            return

        if method == "g2.target.get":
            await self.ws.send_str(make_response(msg_id, self._target_payload()))
            return

        if method == "g2.target.set":
            await self._handle_g2_target_set(msg_id, params)
            return

        if method == "g2.approval.list":
            await self.ws.send_str(make_response(msg_id, {"approvals": self.approvals.pending()}))
            return

        if method == "g2.approval.respond":
            await self._handle_g2_approval_respond(msg_id, params)
            return

        if method == "g2.bootstrap.status":
            await self.ws.send_str(make_response(msg_id, {
                "installed": False,
                "plugin": "hermes-g2",
                "expectedVersion": "0.1.0",
                "installAvailable": True,
                "method": "hermes_plugin_install",
                "message": "Hermes G2 plugin bootstrap is not installed yet.",
            }))
            return

        if method == "g2.action.run":
            await self._handle_g2_action_run(msg_id, params)
            return

        if method.startswith("g2."):
            await self.ws.send_str(make_error(msg_id, 404, f"unknown G2 method: {method}"))
            return

        if method == "chat.send":
            text = params.get("message", "")
            session_key = params.get("sessionKey", self.agent_id)
            await self.ws.send_str(make_response(msg_id, {"accepted": True}))
            asyncio.create_task(self._handle_chat(session_key, text))
            return

        if method == "audio.transcribe":
            await self._handle_audio_transcribe(msg_id, params)
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

    async def _handle_g2_action_run(self, msg_id: str, params: dict):
        action_id = params.get("id", "")
        if not isinstance(action_id, str) or not action_id.strip():
            await self.ws.send_str(make_error(msg_id, 400, "action id is required"))
            return

        action_id = action_id.strip()
        if action_id.startswith("approval:"):
            approval_id = action_id.split(":", 1)[1]
            approval = self.approvals.get(approval_id)
            if approval is None:
                await self.ws.send_str(make_error(msg_id, 404, f"unknown approval: {approval_id}"))
                return
            await self.ws.send_str(make_response(msg_id, {"state": "approval", "approval": approval}))
            return

        surface = self._build_surface(agent_state="busy")
        item = find_surface_item(surface, action_id)
        if item is None:
            await self.ws.send_str(make_error(msg_id, 404, f"unknown action: {action_id}"))
            return

        item_type = item.get("type")
        if item_type == "data":
            await self.ws.send_str(make_response(msg_id, {"state": "detail", "item": item}))
            return

        if item_type == "voice":
            await self.ws.send_str(make_response(msg_id, {"state": "voice", "item": item}))
            return

        if item_type != "action":
            await self.ws.send_str(make_error(msg_id, 400, f"unsupported item type: {item_type}"))
            return

        if action_id == "hex_recon":
            await self._handle_hex_recon_action(msg_id, params)
            return

        prompt = prompt_for_action(action_id)
        if not prompt:
            await self.ws.send_str(make_error(msg_id, 404, f"no prompt configured for action: {action_id}"))
            return

        session_key = params.get("sessionKey", self.agent_id)
        if not isinstance(session_key, str) or not session_key.strip():
            session_key = self.agent_id

        await self.ws.send_str(make_response(msg_id, {
            "accepted": True,
            "state": "running",
            "id": action_id,
            "sessionKey": session_key,
        }))
        asyncio.create_task(self._handle_chat(session_key, prompt))

    def _build_surface(self, agent_state: str = "idle") -> dict:
        return build_default_surface(
            agent_state=agent_state,
            target=self.target,
            pending_approvals=self.approvals.pending(),
        )

    def _target_payload(self) -> dict:
        return {
            "target": self.target.target,
            "scope": self.target.scope,
        }

    async def _handle_g2_target_set(self, msg_id: str, params: dict):
        raw_target = params.get("target", "")
        raw_scope = params.get("scope", "")
        target = raw_target.strip() if isinstance(raw_target, str) else ""
        scope = raw_scope.strip() if isinstance(raw_scope, str) else ""
        if len(target) > 128 or len(scope) > 240:
            await self.ws.send_str(make_error(msg_id, 400, "target or scope is too long"))
            return
        self.target = TargetContext(target=target, scope=scope)
        await self.ws.send_str(make_response(msg_id, self._target_payload()))

    async def _handle_hex_recon_action(self, msg_id: str, params: dict):
        target = self.target.target.strip()
        if not target:
            await self.ws.send_str(make_error(msg_id, 400, "HexStrike target is required"))
            return

        session_key = params.get("sessionKey", self.agent_id)
        if not isinstance(session_key, str) or not session_key.strip():
            session_key = self.agent_id

        prompt = self._hex_recon_prompt()
        if self.approvals.is_granted(target, "hexstrike-recon", "low"):
            await self.ws.send_str(make_response(msg_id, {
                "accepted": True,
                "state": "running",
                "id": "hex_recon",
                "sessionKey": session_key,
                "grant": "session",
            }))
            asyncio.create_task(self._handle_chat(session_key, prompt))
            return

        approval = self.approvals.create_recon_approval(self.target, prompt=prompt)
        await self.ws.send_str(make_response(msg_id, {"state": "approval", "approval": approval}))

    def _hex_recon_prompt(self) -> str:
        scope = self.target.scope.strip() or "authorized security testing scope"
        target = self.target.target.strip()
        return (
            "Use the hexstrike-kali-htb skill. "
            f"Target {target} is authorized under scope: {scope}. "
            "Recover current engagement state, then perform or propose only non-destructive "
            "reconnaissance appropriate to the selected G2 approval grant. "
            "Use HexStrike/Hermes MCP when helpful, keep the final answer concise for G2, "
            "and update the rolling professional report when material observations are found."
        )

    async def _handle_g2_approval_respond(self, msg_id: str, params: dict):
        approval_id = params.get("id", "")
        option_id = params.get("optionId", "")
        if not isinstance(approval_id, str) or not approval_id.strip():
            await self.ws.send_str(make_error(msg_id, 400, "approval id is required"))
            return
        if not isinstance(option_id, str) or not option_id.strip():
            await self.ws.send_str(make_error(msg_id, 400, "approval optionId is required"))
            return

        result = self.approvals.respond(approval_id.strip(), option_id.strip())
        if result.get("state") == "missing":
            await self.ws.send_str(make_error(msg_id, 404, str(result.get("error") or "approval not found")))
            return

        prompt = result.pop("prompt", None)
        session_key = params.get("sessionKey", self.agent_id)
        if not isinstance(session_key, str) or not session_key.strip():
            session_key = self.agent_id
        if result.get("state") == "running":
            result["sessionKey"] = session_key

        await self.ws.send_str(make_response(msg_id, result))
        if isinstance(prompt, str) and prompt:
            asyncio.create_task(self._handle_chat(session_key, prompt))

    async def _handle_audio_transcribe(self, msg_id: str, params: dict):
        audio_b64 = params.get("audioBase64", "")
        mime_type = params.get("mimeType", "audio/wav")
        if not isinstance(audio_b64, str) or not audio_b64:
            await self.ws.send_str(make_error(msg_id, 400, "audioBase64 is required"))
            return

        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError):
            await self.ws.send_str(make_error(msg_id, 400, "audioBase64 is invalid"))
            return

        if len(audio_bytes) > 1_200_000:
            await self.ws.send_str(make_error(msg_id, 413, "audio payload is too large"))
            return

        try:
            stt_model = params.get("sttModel")
            text = await self.hermes.transcribe_audio(
                audio_bytes,
                mime_type=mime_type,
                model=stt_model if isinstance(stt_model, str) and stt_model.strip() else None,
            )
        except Exception as exc:
            logger.error("STT failed for %s: %s", self.conn_id, exc)
            await self.ws.send_str(make_error(msg_id, 502, str(exc)))
            return

        await self.ws.send_str(make_response(msg_id, {"text": text}))

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
        "stt_provider": hermes.stt_provider,
        "local_stt_model": hermes.local_stt_model,
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
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=2**22)
    await ws.prepare(request)

    conn_id = str(uuid.uuid4())[:8]
    conn = BridgeConnection(ws, hermes, conn_id)
    await conn.handle()
    return ws

def create_app(
    hermes_url: str,
    hermes_key: str,
    hermes_model: str,
    hermes_stt_model: str,
    stt_provider: str,
    local_stt_model: str,
    local_stt_device: str,
    local_stt_compute_type: str,
    local_stt_language: Optional[str],
) -> web.Application:
    app = web.Application()
    app["hermes_client"] = HermesClient(
        hermes_url,
        hermes_key,
        hermes_model,
        hermes_stt_model,
        stt_provider=stt_provider,
        local_stt_model=local_stt_model,
        local_stt_device=local_stt_device,
        local_stt_compute_type=local_stt_compute_type,
        local_stt_language=local_stt_language,
    )
    app.router.add_get("/", http_root)
    app.router.add_get("/health", http_health)
    app.router.add_get("/ws", ws_handler)
    return app

# ─── main ────────────────────────────────────────────────────────

async def main_async(args):
    from aiohttp import web
    app = create_app(
        args.hermes_url,
        args.hermes_key,
        args.hermes_model,
        args.hermes_stt_model,
        args.stt_provider,
        args.local_stt_model,
        args.local_stt_device,
        args.local_stt_compute_type,
        args.local_stt_language,
    )

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
    logger.info(
        "Hermes API: %s (chat model: %s, STT provider: %s, Hermes STT model: %s, local STT model: %s)",
        args.hermes_url,
        args.hermes_model,
        args.stt_provider,
        args.hermes_stt_model,
        args.local_stt_model,
    )

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
    parser.add_argument("--hermes-stt-model", default=os.getenv("HERMES_STT_MODEL", "whisper-1"))
    parser.add_argument("--stt-provider", choices=("auto", "hermes", "local"),
                        default=os.getenv("HERMES_STT_PROVIDER", DEFAULT_STT_PROVIDER))
    parser.add_argument("--local-stt-model", default=os.getenv("HERMES_LOCAL_STT_MODEL", DEFAULT_LOCAL_STT_MODEL))
    parser.add_argument("--local-stt-device", default=os.getenv("HERMES_LOCAL_STT_DEVICE", DEFAULT_LOCAL_STT_DEVICE))
    parser.add_argument("--local-stt-compute-type",
                        default=os.getenv("HERMES_LOCAL_STT_COMPUTE_TYPE", DEFAULT_LOCAL_STT_COMPUTE_TYPE))
    parser.add_argument("--local-stt-language", default=os.getenv("HERMES_LOCAL_STT_LANGUAGE") or None)
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
