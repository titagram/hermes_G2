# G2 Info Models Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `g2.info`, model discovery/selection, mobile collapsed configuration sections, an EvenHub reports link, and a first G2 model-picker overlay.

**Architecture:** The bridge exposes structured metadata through `g2.info` and semantic model switching through `g2.models.set`. The app normalizes that metadata in a small TypeScript module, uses it to populate mobile controls, and renders model selection as a G2 overlay without hard-coding server lists. Existing `bridge.capabilities`, `g2.surface`, session recovery, approvals, and voice flows remain backward-compatible.

**Tech Stack:** Python `aiohttp` bridge, OpenClaw-style WebSocket JSON-RPC, TypeScript/Vite EvenHub app, Even Realities G2 SDK containers, Node test runner, Python `unittest`.

---

## File Structure

- Modify `src/bridge_server.py`: add bridge version/report defaults, Hermes model discovery, `g2.info`, and `g2.models.set`.
- Modify `src/g2_surface.py`: read the current report URL from bridge/server environment instead of embedding it only in the app.
- Modify `tests/test_bridge_g2_protocol.py`: protocol tests for `g2.info`, `/models` discovery, report URL exposure, and `g2.models.set`.
- Create `app/src/g2_info.ts`: app-side normalization and formatting for `g2.info`.
- Modify `app/tsconfig.test.json`: include `src/g2_info.ts`.
- Create `app/test/g2-info.test.mjs`: app-side tests for model/report normalization.
- Modify `app/src/mobile_ui.ts`: add release label `v1.0.5 cyber`, section helpers, and report/model help text.
- Modify `app/test/mobile-ui.test.mjs`: assert release label and collapsed section helper output.
- Modify `app/src/main.ts`: fetch `g2.info`, render collapsed mobile sections, populate model dropdowns, add report link, and add G2 model picker screen.
- Modify `app/src/styles.css`: style mobile sections, report link, and dropdown rows without nested card layouts.
- Modify `app/app.json`, `app/package.json`, `app/package-lock.json`: bump app package to `1.0.5`.
- Modify tracked build artifacts `app/dist/index.html` and `app/HermesGlass.ehpk` after verification.

## Task 1: Bridge `g2.info` Contract

**Files:**
- Modify: `src/bridge_server.py`
- Modify: `src/g2_surface.py`
- Test: `tests/test_bridge_g2_protocol.py`

- [ ] **Step 1: Write failing tests**

Add tests to `tests/test_bridge_g2_protocol.py`:

```python
async def test_g2_info_returns_models_reports_and_capabilities(self):
    ws = FakeWs()
    hermes = FakeHermes()
    hermes.available_models = ["gemma4:local", "qwen-coder"]
    hermes.model = "gemma4:local"
    conn = BridgeConnection(ws, hermes, "test")

    await conn._handle_request({"method": "g2.info", "params": {}}, "info-1")

    response = ws.sent[-1]
    self.assertEqual(response["ok"], True)
    payload = response["payload"]
    self.assertEqual(payload["capabilities"]["models"], True)
    self.assertEqual(payload["models"]["llm"]["current"], "gemma4:local")
    self.assertEqual([item["id"] for item in payload["models"]["llm"]["available"]], ["gemma4:local", "qwen-coder"])
    self.assertEqual(payload["models"]["llm"]["available"][0]["active"], True)
    self.assertIn("reports", payload)
    self.assertTrue(payload["reports"]["current"]["url"].startswith("https://"))
    self.assertEqual(payload["models"]["tts"]["available"], [])

async def test_g2_info_includes_current_model_when_models_endpoint_misses_it(self):
    ws = FakeWs()
    hermes = FakeHermes()
    hermes.available_models = ["qwen-coder"]
    hermes.model = "gemma4:local"
    conn = BridgeConnection(ws, hermes, "test")

    await conn._handle_request({"method": "g2.info", "params": {}}, "info-2")

    llm = ws.sent[-1]["payload"]["models"]["llm"]
    self.assertEqual(llm["current"], "gemma4:local")
    self.assertIn("gemma4:local", [item["id"] for item in llm["available"]])
    self.assertTrue(next(item for item in llm["available"] if item["id"] == "gemma4:local")["active"])
```

Update `FakeHermes` with:

```python
model = "hermes-agent"
available_models = ["hermes-agent"]

async def list_models(self):
    return list(self.available_models), "/models"
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_bridge_g2_protocol
```

Expected: FAIL with unknown `g2.info` or missing model/report payload.

- [ ] **Step 3: Implement bridge info**

In `src/bridge_server.py`, add constants:

```python
BRIDGE_VERSION = "1.0.5"
DEFAULT_REPORT_URL = "https://titagram.tail005130.ts.net:8899/engagements/current/"
DEFAULT_LOCAL_STT_MODELS = ("tiny", "base", "small", "medium", "large-v3")
```

Add to `HermesClient`:

```python
async def list_models(self) -> tuple[list[str], str]:
    for path in ("/models", "/v1/models"):
        try:
            models = await self._fetch_models(path)
        except Exception as exc:
            logger.warning("Hermes model discovery failed at %s: %s", path, exc)
            continue
        if models:
            return models, path
    return [], "configured"

async def _fetch_models(self, path: str) -> list[str]:
    session = await self._get_session()
    async with session.get(f"{self.base_url}{path}") as resp:
        if resp.status != 200:
            raise RuntimeError(f"{path} returned {resp.status}")
        data = await resp.json()
    return _extract_model_ids(data)
```

Add a module helper:

```python
def _extract_model_ids(data: Any) -> list[str]:
    raw_items = data.get("data") if isinstance(data, dict) else data
    if isinstance(data, dict) and raw_items is None:
        raw_items = data.get("models")
    if not isinstance(raw_items, list):
        return []
    ids: list[str] = []
    for item in raw_items:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id.strip():
            cleaned = model_id.strip()
            if cleaned not in ids:
                ids.append(cleaned)
    return ids
```

Add to `BridgeConnection`:

```python
async def _handle_g2_info(self, msg_id: str):
    await self.ws.send_str(make_response(msg_id, await self._build_info()))

async def _build_info(self) -> dict[str, Any]:
    llm_models, source = await self.hermes.list_models()
    current = self.hermes.model
    llm_available = self._model_options(llm_models, current)
    stt_current = self.hermes.local_stt_model if self.hermes.stt_provider == "local" else self.hermes.stt_model
    stt_available = self._model_options(list(DEFAULT_LOCAL_STT_MODELS), stt_current)
    report_url = os.getenv("HERMES_G2_REPORT_URL", DEFAULT_REPORT_URL).strip()
    reports = {"current": {"label": "Current engagement report", "url": report_url, "source": "bridge"}} if report_url else {}
    return {
        "server": {"name": "hermes-glass", "version": BRIDGE_VERSION, "protocol": PROTOCOL_VERSION},
        "capabilities": {
            "surface": True, "approvals": True, "sessionResume": True,
            "audioTranscribe": True, "models": True, "tts": False,
        },
        "reports": reports,
        "models": {
            "llm": {"current": current, "canSet": True, "source": source, "available": llm_available},
            "stt": {
                "provider": self.hermes.stt_provider,
                "current": stt_current,
                "canSet": False,
                "source": "bridge",
                "available": stt_available,
            },
            "tts": {"provider": None, "current": None, "canSet": False, "source": None, "available": []},
        },
    }

def _model_options(self, model_ids: list[str], current: str) -> list[dict[str, Any]]:
    ids = [item for item in model_ids if item]
    if current and current not in ids:
        ids.insert(0, current)
    return [{"id": item, "label": item, "active": item == current} for item in ids]
```

Route `g2.info` before unknown `g2.*`.

- [ ] **Step 4: Run bridge tests**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_bridge_g2_protocol tests.test_bridge_stt
```

Expected: PASS.

## Task 2: Bridge Model Selection

**Files:**
- Modify: `src/bridge_server.py`
- Test: `tests/test_bridge_g2_protocol.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
async def test_g2_models_set_updates_current_llm_model(self):
    ws = FakeWs()
    hermes = FakeHermes()
    hermes.available_models = ["gemma4:local", "qwen-coder"]
    hermes.model = "gemma4:local"
    conn = BridgeConnection(ws, hermes, "test")

    await conn._handle_request({
        "method": "g2.models.set",
        "params": {"family": "llm", "modelId": "qwen-coder"},
    }, "model-set")

    response = ws.sent[-1]
    self.assertEqual(response["ok"], True)
    self.assertEqual(hermes.model, "qwen-coder")
    self.assertEqual(response["payload"]["models"]["llm"]["current"], "qwen-coder")

async def test_g2_models_set_rejects_unknown_model(self):
    ws = FakeWs()
    hermes = FakeHermes()
    hermes.available_models = ["gemma4:local"]
    conn = BridgeConnection(ws, hermes, "test")

    await conn._handle_request({
        "method": "g2.models.set",
        "params": {"family": "llm", "modelId": "missing"},
    }, "model-missing")

    response = ws.sent[-1]
    self.assertEqual(response["ok"], False)
    self.assertEqual(response["error"]["code"], 404)
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_bridge_g2_protocol
```

Expected: FAIL with unknown `g2.models.set`.

- [ ] **Step 3: Implement `g2.models.set`**

Add a route:

```python
if method == "g2.models.set":
    await self._handle_g2_models_set(msg_id, params)
    return
```

Add:

```python
async def _handle_g2_models_set(self, msg_id: str, params: dict):
    family = params.get("family")
    model_id = params.get("modelId")
    if family != "llm":
        await self.ws.send_str(make_error(msg_id, 400, "only llm model switching is supported"))
        return
    if not isinstance(model_id, str) or not model_id.strip():
        await self.ws.send_str(make_error(msg_id, 400, "modelId is required"))
        return
    requested = model_id.strip()
    models, _ = await self.hermes.list_models()
    if requested not in models and requested != self.hermes.model:
        await self.ws.send_str(make_error(msg_id, 404, f"unknown model: {requested}"))
        return
    self.hermes.model = requested
    await self.ws.send_str(make_response(msg_id, await self._build_info()))
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_bridge_g2_protocol tests.test_bridge_stt
```

Expected: PASS.

## Task 3: App `g2.info` Normalization

**Files:**
- Create: `app/src/g2_info.ts`
- Create: `app/test/g2-info.test.mjs`
- Modify: `app/tsconfig.test.json`

- [ ] **Step 1: Write failing tests**

Create `app/test/g2-info.test.mjs`:

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_G2_INFO,
  formatModelRow,
  normalizeG2Info,
} from '../dist-test/g2_info.js'

test('normalizes g2 info with model families and report link', () => {
  const info = normalizeG2Info({
    server: { name: 'hermes-glass', version: '1.0.5', protocol: 3 },
    reports: { current: { label: 'Reports', url: 'https://reports.example/current/', source: 'bridge' } },
    models: {
      llm: {
        current: 'gemma4:local',
        canSet: true,
        source: '/models',
        available: [
          { id: 'gemma4:local', label: 'Gemma 4', active: true },
          { id: 'qwen-coder', label: 'Qwen Coder', active: false },
        ],
      },
      stt: { provider: 'local', current: 'tiny', canSet: false, source: 'bridge', available: [] },
      tts: { provider: null, current: null, canSet: false, source: null, available: [] },
    },
  })

  assert.equal(info.server.version, '1.0.5')
  assert.equal(info.reports.current?.url, 'https://reports.example/current/')
  assert.equal(info.models.llm.available.length, 2)
  assert.equal(formatModelRow(info.models.llm.available[0]), 'Gemma 4 current')
})

test('falls back to safe empty g2 info', () => {
  const info = normalizeG2Info(null)

  assert.deepEqual(info, DEFAULT_G2_INFO)
})
```

Add `src/g2_info.ts` to `app/tsconfig.test.json`.

- [ ] **Step 2: Run app tests to verify red**

Run:

```bash
npm test
```

Expected: FAIL because `dist-test/g2_info.js` does not exist.

- [ ] **Step 3: Implement normalization**

Create `app/src/g2_info.ts` with exported `DEFAULT_G2_INFO`, `normalizeG2Info`, and `formatModelRow`. Keep all strings trimmed, URLs limited to `http://` or `https://`, and model rows clipped to 64 chars.

- [ ] **Step 4: Run app tests**

Run:

```bash
npm test
```

Expected: PASS.

## Task 4: Mobile Collapsed Sections and Report Link

**Files:**
- Modify: `app/src/mobile_ui.ts`
- Modify: `app/src/main.ts`
- Modify: `app/src/styles.css`
- Modify: `app/test/mobile-ui.test.mjs`

- [ ] **Step 1: Write failing tests**

Extend `app/test/mobile-ui.test.mjs`:

```javascript
import { configSection } from '../dist-test/mobile_ui.js'

test('mobile UI renders collapsed config sections by default', () => {
  const html = configSection('Profile', 'Default', '<input id="x">')

  assert.match(html, /<details class="config-section">/)
  assert.doesNotMatch(html, / open>/)
  assert.match(html, /<summary>/)
  assert.match(html, /Default/)
})
```

Update the existing release test to expect `v1.0.5 cyber` and manifest `1.0.5`.

- [ ] **Step 2: Run app tests to verify red**

Run:

```bash
npm test
```

Expected: FAIL because `configSection` and `1.0.5` are missing.

- [ ] **Step 3: Implement mobile UI**

In `app/src/mobile_ui.ts`, add:

```typescript
export const APP_RELEASE_LABEL = 'v1.0.5 cyber'

export function configSection(title: string, meta: string, body: string): string {
  return `<details class="config-section"><summary><span>${title}</span><span class="drawer-meta">${meta}</span></summary><div class="section-body">${body}</div></details>`
}
```

In `app/src/main.ts`, group existing inputs into `Profile`, `Input`, `Target`, `Models`, and `Controls` sections. Keep `#fieldHelpPanel` below all sections. Add an anchor:

```html
<a id="reportLink" class="report-link" href="#" target="_blank" rel="noopener" hidden>Open Reports</a>
```

Populate it from runtime `g2.info.reports.current.url`; hide it when absent.

- [ ] **Step 4: Run app tests**

Run:

```bash
npm test
```

Expected: PASS.

## Task 5: App Model Dropdowns and G2 Model Picker Overlay

**Files:**
- Modify: `app/src/main.ts`
- Modify: `app/src/surface.ts`
- Modify: `app/test/surface.test.mjs`

- [ ] **Step 1: Write failing tests**

Add to `app/test/surface.test.mjs`:

```javascript
test('normalizes model action surface items', () => {
  const surface = normalizeSurface({
    items: [
      { id: 'model', type: 'action', label: 'MODEL', summary: 'gemma4:local', priority: 22, action: { kind: 'model_picker', confirm: false, risk: 'read_only' } },
    ],
  })

  assert.equal(surface.items[0].action?.kind, 'model_picker')
  assert.equal(formatHomeRow(surface.items[0]), 'MODEL gemma4:local')
})
```

- [ ] **Step 2: Run app tests**

Run:

```bash
npm test
```

Expected: PASS or FAIL depending on existing generic action normalization. If PASS, continue because main renderer still needs implementation.

- [ ] **Step 3: Implement model picker**

In `HermesBridgeClient`, add:

```typescript
async getInfo(): Promise<G2Info> {
  return normalizeG2Info(await this.sendRequest('g2.info', {}, 10000))
}

async setModel(modelId: string): Promise<G2Info> {
  return normalizeG2Info(await this.sendRequest('g2.models.set', { family: 'llm', modelId }, 20000))
}
```

On connect, call `getInfo()` before session resume. Store it in `bridgeInfo`.

Add `type Screen` value `models`, selected model index state, `buildModelPickerText()`, `showModelPicker()`, and `chooseModelOption()`. Route a surface item with `action.kind === 'model_picker'` to `showModelPicker()`. If the bridge surface does not include a model item yet, append a client-side `MODEL` row from `bridgeInfo.models.llm.current` before rendering.

- [ ] **Step 4: Run app tests and build**

Run:

```bash
npm test
npm run build
```

Expected: PASS.

## Task 6: Server Surface Model Item

**Files:**
- Modify: `src/g2_surface.py`
- Modify: `src/bridge_server.py`
- Test: `tests/test_g2_surface.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_g2_surface.py`:

```python
def test_default_surface_includes_model_picker_when_model_is_known(self):
    surface = build_default_surface(model="gemma4:local")
    model = find_surface_item(surface, "model")

    self.assertIsNotNone(model)
    self.assertEqual(model["label"], "MODEL")
    self.assertEqual(model["summary"], "gemma4:local")
    self.assertEqual(model["action"]["kind"], "model_picker")
```

- [ ] **Step 2: Run test to verify red**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface
```

Expected: FAIL because `build_default_surface()` has no `model` argument.

- [ ] **Step 3: Implement model surface item**

Add `model_picker_item(model: str)` and include it in `build_default_surface()` when a model string is present. Pass `self.hermes.model` from `BridgeConnection._build_surface()`.

- [ ] **Step 4: Run server tests**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface tests.test_bridge_g2_protocol
```

Expected: PASS.

## Task 7: Package, Probe, and Commit

**Files:**
- Modify generated: `app/dist/index.html`
- Modify generated: `app/HermesGlass.ehpk`

- [ ] **Step 1: Full local verification**

Run:

```bash
PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_approval tests.test_g2_hexstrike tests.test_g2_state tests.test_g2_jobs tests.test_g2_surface tests.test_bridge_g2_protocol tests.test_bridge_stt
npm test
npm run build
npx evenhub pack app.json dist -o HermesGlass.ehpk
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Optional server probe**

When SSH is reachable:

```bash
ssh titagram@192.168.2.148 'curl -fsS http://127.0.0.1:8642/models || curl -fsS http://127.0.0.1:8642/v1/models'
```

Expected: JSON model list or a clear HTTP failure that confirms fallback behavior is needed.

- [ ] **Step 3: Commit**

Commit implementation and generated package:

```bash
git add src/bridge_server.py src/g2_surface.py tests/test_bridge_g2_protocol.py tests/test_g2_surface.py app/src/g2_info.ts app/src/mobile_ui.ts app/src/main.ts app/src/styles.css app/src/surface.ts app/test/g2-info.test.mjs app/test/mobile-ui.test.mjs app/test/surface.test.mjs app/tsconfig.test.json app/app.json app/package.json app/package-lock.json app/dist/index.html app/HermesGlass.ehpk
git commit -m "feat: add G2 info models and mobile sections"
```

Expected: commit succeeds on `G2-hermes-cyber`.
