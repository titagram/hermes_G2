# Hermes G2 Channel Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first server-driven Hermes G2 channel slice: semantic surface/actions from the bridge, G2 list/detail/confirm rendering, mobile multi-profile basics, and testable contracts.

**Architecture:** The bridge exposes semantic `g2.*` methods over the existing OpenClaw WebSocket. The EvenHub app stores connection profiles locally, connects to one active profile, renders fixed G2 UI primitives from server-provided actions/data, and sends action ids back to the bridge. Hermes-native plugin/bootstrap remains a protocol scaffold in this phase; full upstream plugin installation is deferred.

**Tech Stack:** Python 3.12 `aiohttp` bridge, TypeScript/Vite EvenHub app, `@evenrealities/even_hub_sdk`, Node test runner, Python `unittest`.

---

## File Map

- `src/g2_surface.py`: new bridge-side semantic surface model, default items, server stats, and action lookup.
- `src/bridge_server.py`: add `g2.surface.get`, `g2.surface.refresh`, `g2.action.run`, and `g2.bootstrap.status`; include `g2Surface` capability.
- `tests/test_g2_surface.py`: Python tests for default surface, server stats shape, action lookup, and action safety metadata.
- `tests/test_bridge_g2_protocol.py`: Python async tests for bridge request behavior using fake connections/Hermes client.
- `test_bridge.py`: extend probe to print G2 surface and optionally run an action.
- `app/src/config.ts`: add profile model, token field, active profile helpers, and backward-compatible config parsing.
- `app/src/surface.ts`: new TypeScript types and normalization/pagination helpers for semantic items.
- `app/src/events.ts`: add list event normalization so native list press can select indexed items.
- `app/src/main.ts`: render home/list/detail/confirm/running/voice from surface; connect to active profile; run actions by id.
- `app/src/styles.css`: mobile profile management UI styling.
- `app/test/config.test.mjs`, `app/test/events.test.mjs`, `app/test/surface.test.mjs`: app-side contract tests.
- `README.md`: update phase 1 usage and protocol docs after implementation.

## Task 1: Bridge Semantic Surface Model

**Files:**
- Create: `src/g2_surface.py`
- Create: `tests/test_g2_surface.py`

- [ ] **Step 1: Write failing tests for default surface**

Create `tests/test_g2_surface.py` with tests asserting:

```python
from src.g2_surface import build_default_surface, find_surface_item


def test_default_surface_has_voice_and_actions():
    surface = build_default_surface()
    labels = [item["label"] for item in surface["items"]]
    assert "VOICE" in labels
    assert "MAIL" in labels
    assert "DAILY" in labels
    assert surface["version"] == 1
    assert surface["status"]["agent"] in {"idle", "busy"}


def test_action_metadata_stays_server_side():
    surface = build_default_surface()
    mail = find_surface_item(surface, "mail")
    assert mail is not None
    assert mail["type"] == "action"
    assert mail["action"]["confirm"] is False
    assert mail["action"]["risk"] == "read_only"
    assert "prompt" not in mail
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface`

Expected: FAIL because `src.g2_surface` does not exist.

- [ ] **Step 3: Implement minimal surface model**

Create `src/g2_surface.py` with:

```python
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional


Surface = Dict[str, Any]


DEFAULT_ACTION_PROMPTS = {
    "mail": "Read my important unread email and summarize what needs action.",
    "daily": "Give me my daily briefing for today.",
}


def _read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                key, raw = line.split(":", 1)
                value = raw.strip().split()[0]
                if value.isdigit():
                    result[key] = int(value)
    except OSError:
        return {}
    return result


def _memory_summary() -> str:
    mem = _read_meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    if total <= 0 or available < 0:
        return "RAM n/a"
    used_pct = round((1 - available / total) * 100)
    return f"RAM {used_pct}%"


def _load_summary() -> str:
    try:
        load1, _, _ = os.getloadavg()
        return f"LOAD {load1:.2f}"
    except OSError:
        return "LOAD n/a"


def server_status_item() -> dict[str, Any]:
    load = _load_summary()
    memory = _memory_summary()
    return {
        "id": "server",
        "type": "data",
        "label": "SERVER",
        "summary": f"{load} {memory}",
        "detail": f"Server status\\n{load}\\n{memory}",
        "priority": 30,
    }


def build_default_surface(agent_state: str = "idle") -> Surface:
    now = int(time.time() * 1000)
    return {
        "version": 1,
        "updatedAt": now,
        "status": {"agent": agent_state, "connection": "ok"},
        "items": [
            server_status_item(),
            {
                "id": "mail",
                "type": "action",
                "label": "MAIL",
                "summary": "important unread",
                "priority": 20,
                "action": {"kind": "run_prompt", "confirm": False, "risk": "read_only"},
            },
            {
                "id": "daily",
                "type": "action",
                "label": "DAILY",
                "summary": "briefing",
                "priority": 10,
                "action": {"kind": "run_prompt", "confirm": False, "risk": "read_only"},
            },
            {
                "id": "voice",
                "type": "voice",
                "label": "VOICE",
                "summary": "press to talk",
                "priority": 0,
            },
        ],
    }


def find_surface_item(surface: Surface, item_id: str) -> Optional[dict[str, Any]]:
    for item in surface.get("items", []):
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def prompt_for_action(action_id: str) -> Optional[str]:
    return DEFAULT_ACTION_PROMPTS.get(action_id)
```

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface`

Expected: 2 tests pass.

## Task 2: Bridge G2 Protocol Methods

**Files:**
- Modify: `src/bridge_server.py`
- Create: `tests/test_bridge_g2_protocol.py`
- Modify: `test_bridge.py`

- [ ] **Step 1: Write failing protocol tests**

Create `tests/test_bridge_g2_protocol.py` with async tests that instantiate `BridgeConnection` with a fake WebSocket and fake Hermes client:

```python
import json
import unittest

from src.bridge_server import BridgeConnection


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_str(self, value):
        self.sent.append(json.loads(value))


class FakeHermes:
    stt_model = "whisper-1"
    stt_provider = "local"
    local_stt_model = "tiny"

    def __init__(self):
        self.messages = []

    async def chat_stream(self, message, session_id=None):
        self.messages.append(message)
        yield (None, "ok", "stop")


class BridgeG2ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_surface_get_returns_semantic_items(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")
        await conn._handle_request({"method": "g2.surface.get", "params": {}}, "surface-1")
        response = ws.sent[-1]
        assert response["ok"] is True
        assert response["payload"]["version"] == 1
        assert any(item["id"] == "voice" for item in response["payload"]["items"])

    async def test_action_run_rejects_unknown_action(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")
        await conn._handle_request({"method": "g2.action.run", "params": {"id": "missing"}}, "run-1")
        response = ws.sent[-1]
        assert response["ok"] is False
        assert response["error"]["code"] == 404

    async def test_bootstrap_status_is_structured(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")
        await conn._handle_request({"method": "g2.bootstrap.status", "params": {}}, "boot-1")
        response = ws.sent[-1]
        assert response["ok"] is True
        assert response["payload"]["plugin"] == "hermes-g2"
        assert "installed" in response["payload"]
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_bridge_g2_protocol`

Expected: FAIL because the `g2.*` methods are not handled.

- [ ] **Step 3: Implement bridge methods**

In `src/bridge_server.py`:

- Import `build_default_surface`, `find_surface_item`, `prompt_for_action`.
- Add `g2Surface`, `bootstrap`, and `surfaceVersion` to `bridge.capabilities`.
- Handle:
  - `g2.surface.get` and `g2.surface.refresh`: return `build_default_surface()`.
  - `g2.bootstrap.status`: return structured status with `installed=False`, `installAvailable=True`, `plugin="hermes-g2"`, `expectedVersion="0.1.0"`.
  - `g2.action.run`: look up item id. For `data`, return `{"state": "detail", "item": item}`. For `voice`, return `{"state": "voice"}`. For prompt actions, ack accepted and start `_handle_chat(session_key, prompt)`.

- [ ] **Step 4: Extend `test_bridge.py` probe**

Add flags:

- `--surface`: request `g2.surface.get` and print item count plus labels.
- `--run-action ACTION_ID`: send `g2.action.run` for the id and print response.

- [ ] **Step 5: Verify Python tests**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface tests.test_bridge_g2_protocol tests.test_bridge_stt
/tmp/hermes-g2-test-venv/bin/python -m py_compile src/bridge_server.py src/g2_surface.py test_bridge.py
```

Expected: all tests pass and py_compile exits 0.

## Task 3: App Config Profiles

**Files:**
- Modify: `app/src/config.ts`
- Modify: `app/test/config.test.mjs`

- [ ] **Step 1: Add failing profile tests**

Extend `app/test/config.test.mjs` with tests for:

- Parsing multiple profiles.
- Active profile fallback.
- Token trimming.
- Backward compatibility with existing `bridgeUrl`.

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test` from `app/`.

Expected: FAIL until profile helpers exist.

- [ ] **Step 3: Implement profile helpers**

In `app/src/config.ts`, add:

- `ConnectionProfile` type.
- `DEFAULT_PROFILE_ID`.
- `activeProfile(config)`.
- `upsertProfile(config, profile)`.
- `deleteProfile(config, profileId)`.
- Extend `AppConfig` with `profiles`, `activeProfileId`.
- Keep `bridgeUrl` and token-compatible fields for old code during migration.

- [ ] **Step 4: Verify tests**

Run: `npm test` from `app/`.

Expected: config tests pass with the rest of the app tests.

## Task 4: Surface Normalization And Event Selection

**Files:**
- Create: `app/src/surface.ts`
- Create: `app/test/surface.test.mjs`
- Modify: `app/src/events.ts`
- Modify: `app/test/events.test.mjs`

- [ ] **Step 1: Write failing surface/event tests**

Create `app/test/surface.test.mjs` covering:

- Invalid surface normalizes to empty items and `connection=unknown`.
- Labels are uppercase and clipped for G2 list rows.
- `formatHomeRow(item)` returns short rows such as `MAIL 12 unread`.

Extend `app/test/events.test.mjs` with:

- `listEvent.currentSelectItemIndex` is normalized to `selectedIndex`.
- Missing zero index falls back to 0.

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test` from `app/`.

Expected: FAIL until `surface.ts` and list normalization exist.

- [ ] **Step 3: Implement `surface.ts` and event fields**

Add TS types:

- `SurfaceItem`
- `G2Surface`
- `normalizeSurface`
- `formatHomeRow`
- `paginateDetail`

Extend `NormalizedHubEvent` with `selectedIndex: number | null` from `listEvent`.

- [ ] **Step 4: Verify tests**

Run: `npm test` from `app/`.

Expected: all app tests pass.

## Task 5: G2 Home/List/Detail/Confirm Renderer

**Files:**
- Modify: `app/src/main.ts`
- Modify: `app/src/styles.css`

- [ ] **Step 1: Add bridge client methods**

In `HermesBridgeClient`, add:

- `getSurface(): Promise<G2Surface>`
- `refreshSurface(): Promise<G2Surface>`
- `runAction(id: string): Promise<Record<string, unknown>>`
- `getBootstrapStatus(): Promise<Record<string, unknown>>`

- [ ] **Step 2: Add screen states**

Replace narrow chat-only state with screen modes:

- `config`
- `home`
- `detail`
- `confirm`
- `listening`
- `thinking`
- `showing`
- `error`

Preserve existing voice capture functions.

- [ ] **Step 3: Render native list home**

Use `ListContainerProperty` and `ListItemContainerProperty` for home when possible:

- Full-width list container from y=0 to y=240.
- Status text container y=244 height=44.
- List rows are `formatHomeRow(item)`.
- `isEventCapture=1` on list.

If list rendering fails, fall back to text rows with `>` cursor.

- [ ] **Step 4: Implement item activation**

On selected home item:

- `type=data`: show detail pages.
- `type=voice`: start voice recording.
- `type=action` with `confirm=true` or high risk: show confirm.
- `type=action` read-only: call `g2.action.run`, show running, then stream chat result.

- [ ] **Step 5: Implement back behavior**

- Double press on `detail`, `confirm`, `showing`, or `error`: return home.
- Double press on `home`: show system exit dialog or navigate to an `EXIT` item if hardware testing rejects double-press exit.

- [ ] **Step 6: Verify build**

Run:

```bash
cd app
npm test
npm run build
```

Expected: tests and build pass.

## Task 6: Mobile Profile Management UI

**Files:**
- Modify: `app/src/main.ts`
- Modify: `app/src/styles.css`

- [ ] **Step 1: Add mobile controls**

Add phone-side controls:

- Profile select.
- Profile name.
- WebSocket URL.
- Token.
- Buttons: `New Profile`, `Save Profile`, `Delete Profile`, `Connect`.

- [ ] **Step 2: Wire controls to config helpers**

Save profiles through `bridge.setLocalStorage(CONFIG_STORAGE_KEY, serializeAppConfig(appConfig))`.

Do not show token in G2 display preview or surface JSON.

- [ ] **Step 3: Test manually in browser/simulator**

Run the Vite app and EvenHub simulator. Verify:

- A second profile can be added.
- Switching profile changes active URL.
- Existing single URL config still loads as the default profile.

## Task 7: Docs, Pack, And Simulator Verification

**Files:**
- Modify: `README.md`
- Modify: `app/HermesGlass.ehpk`

- [ ] **Step 1: Update README**

Document:

- `g2.surface.get`
- `g2.action.run`
- profiles
- bootstrap status
- current hardware-test boundary for long press/ring/list selection.

- [ ] **Step 2: Run full verification**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface tests.test_bridge_g2_protocol tests.test_bridge_stt
/tmp/hermes-g2-test-venv/bin/python -m py_compile src/bridge_server.py src/g2_surface.py test_bridge.py
cd app && npm test && npm run build && npx evenhub pack app.json dist -o HermesGlass.ehpk
```

Expected: all commands exit 0.

- [ ] **Step 3: Simulator smoke test**

Run:

```bash
cd app
npm run dev -- --host 127.0.0.1
evenhub-simulator -g --automation-port 9904 http://127.0.0.1:5173
```

Verify:

- App starts and shows config/profile UI.
- Connect shows G2 home list.
- Selecting `SERVER` opens detail.
- Selecting `VOICE` reaches listening state.
- Selecting `MAIL` sends a server-driven action.

- [ ] **Step 4: Stop at human-test boundary**

Human hardware tests still required:

- Ring source distinction.
- Native list selection behavior on real G2/R1.
- Whether long press is delivered to plugins.
- Preferred exit gesture after double press becomes back.
