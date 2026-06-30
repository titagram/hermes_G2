# G2 Display UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the glasses display from a mostly plain chat/list view into the operational Hermes dashboard described in `docs/superpowers/specs/2026-06-27-g2-display-ux-design.md`.

**Architecture:** Add a pure TypeScript display-formatting module that produces dashboard, decision, and status text primitives independent from the EvenHub SDK. `main.ts` keeps owning SDK container creation, bridge calls, and input events, but uses the new module for all G2-facing copy and layout decisions.

**Tech Stack:** TypeScript/Vite EvenHub app, `@evenrealities/even_hub_sdk` text/list containers, Node test runner.

---

### Task 1: Pure G2 Display Formatting

**Files:**
- Create: `app/src/g2_display.ts`
- Modify: `app/tsconfig.test.json`
- Test: `app/test/g2-display.test.mjs`

- [ ] **Step 1: Write failing tests**

```js
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildApprovalDecisionText,
  buildDashboardView,
  buildVoiceStatusText,
  cleanForG2,
} from '../dist-test/g2_display.js'

test('builds dashboard header rows and hint for an operational home screen', () => {
  const view = buildDashboardView({
    version: 1,
    updatedAt: 1,
    status: { agent: 'idle', connection: 'ok' },
    items: [
      { id: 'hex_recon', type: 'action', label: 'RECON', summary: '192.168.1.1', priority: 24 },
      { id: 'server', type: 'data', label: 'SERVER', summary: 'LOAD 0.12 RAM 39%', priority: 30 },
      { id: 'voice', type: 'voice', label: 'VOICE', summary: 'press to talk', priority: 0 },
    ],
  }, 1)

  assert.equal(view.header, 'HERMES OK | IDLE | 192.168.1.1')
  assert.deepEqual(view.rows, ['SERVER LOAD 0.12 RAM 39%', 'RECON 192.168.1.1', 'VOICE press to talk'])
  assert.equal(view.hint, '2/3 RECON | press select | double exit')
})

test('builds compact approval decision text with selected option', () => {
  const text = buildApprovalDecisionText({
    id: 'appr_1',
    title: 'Quick recon',
    target: '192.168.1.1',
    workflow: 'hexstrike-recon',
    risk: 'low',
    reason: 'Run bounded HexStrike recon',
    detail: '',
    options: [
      { id: 'once', label: 'ONCE', kind: 'approve_once' },
      { id: 'session-low', label: 'SESSION LOW', kind: 'approve_session', ttlMinutes: 30, riskCeiling: 'low' },
      { id: 'deny', label: 'DENY', kind: 'deny' },
    ],
  }, 1)

  assert.match(text, /^APPROVAL LOW\nQuick recon\n192\.168\.1\.1/)
  assert.match(text, /> SESSION LOW 30m low/)
})

test('cleans markdown and urls for the firmware font', () => {
  assert.equal(cleanForG2('**Done** see https://example.test/x and `code`'), 'Done see [link] and code')
})

test('builds voice status text with timeout context', () => {
  assert.equal(buildVoiceStatusText('listening', 15), 'LISTENING\nSpeak now\n\ntimeout 15s')
  assert.equal(buildVoiceStatusText('stt-error', 15, 'Hermes STT API error 404'), 'STT ERROR\nHermes STT API error 404\n\ntap/ring retry')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && npm test -- --test-name-pattern="dashboard|approval|cleans|voice"`

Expected: FAIL because `dist-test/g2_display.js` does not exist.

- [ ] **Step 3: Implement `app/src/g2_display.ts`**

Create pure helpers:
- `cleanForG2(text)`
- `buildDashboardView(surface, selectedIndex)`
- `buildApprovalDecisionText(approval, selectedIndex)`
- `buildVoiceStatusText(state, timeoutSeconds, message?)`
- `buildStatusPageText(title, lines)`

- [ ] **Step 4: Include module in test build**

Add `src/g2_display.ts` to `app/tsconfig.test.json`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app && npm test`

Expected: PASS.

### Task 2: SDK Container Templates in `main.ts`

**Files:**
- Modify: `app/src/main.ts`
- Test: `app/test/g2-display.test.mjs`

- [ ] **Step 1: Write/extend failing tests for dimensions**

Add assertions that dashboard dimensions expose a 36 px header, 212 px list, and 40 px hint.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && npm test -- --test-name-pattern="dashboard dimensions"`

Expected: FAIL because constants are missing.

- [ ] **Step 3: Implement dashboard containers**

In `main.ts`, replace home rendering with:
- top text container `g2Header`, 36 px high;
- center native list `g2List`, 212 px high;
- bottom text container `g2Hint`, 40 px high;
- exactly one event capture container on the list.

- [ ] **Step 4: Update fallback text layout**

Fallback should show the dashboard header, selected rows, and hint as plain text if native list rendering fails.

- [ ] **Step 5: Run tests**

Run: `cd app && npm test`

Expected: PASS.

### Task 3: Apply New Text Hierarchy to State Screens

**Files:**
- Modify: `app/src/main.ts`
- Test: `app/test/g2-display.test.mjs`

- [ ] **Step 1: Write failing tests for voice and status copy**

Covered by Task 1 helpers.

- [ ] **Step 2: Replace inline screen copy**

Use the helper output for:
- config;
- connecting/reconnecting;
- approval;
- model picker;
- running action;
- voice listening/transcribing/STT error;
- chat final/pagination status.

- [ ] **Step 3: Run app tests**

Run: `cd app && npm test`

Expected: PASS.

### Task 4: Build and Package

**Files:**
- Modify: `app/dist/index.html`
- Modify: `app/HermesGlass.ehpk`
- Modify: `app/app.json`
- Modify: `app/package.json`
- Modify: `app/package-lock.json`

- [ ] **Step 1: Bump app version**

Bump from `1.0.5` to `1.0.6`.

- [ ] **Step 2: Build**

Run: `cd app && npm run build`

Expected: Vite build succeeds.

- [ ] **Step 3: Pack EvenHub app**

Run: `cd app && npx evenhub pack app.json dist -o HermesGlass.ehpk`

Expected: `Successfully packed HermesGlass.ehpk`.

### Task 5: Final Verification

**Files:**
- All touched files.

- [ ] **Step 1: Run full app verification**

Run: `cd app && npm test && npm run build && npx evenhub pack app.json dist -o HermesGlass.ehpk`

Expected: PASS.

- [ ] **Step 2: Run diff checks**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended files changed.
