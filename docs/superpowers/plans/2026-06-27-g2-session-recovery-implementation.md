# G2 Session Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement durable G2 session recovery so pending approvals, grants, active HexStrike jobs, recent events, and job/report status survive glasses WebSocket disconnects.

**Architecture:** Add a SQLite-backed `G2StateStore` for sessions/events/approvals/grants/jobs and a bridge-owned `G2JobManager` that runs HexStrike jobs independently of a single WebSocket. The EvenHub app gets a stable `clientSessionId`, calls `g2.session.resume`, stores `lastSeenEventId`, and renders restored active jobs through the existing server-driven surface.

**Tech Stack:** Python stdlib `sqlite3`, `asyncio` subprocesses, current aiohttp WebSocket bridge, TypeScript EvenHub app, Node test runner, Python unittest.

---

## File Structure

- Create `src/g2_state.py`: SQLite schema, session resume, event append/query, approval/grant/job persistence.
- Create `src/g2_jobs.py`: durable in-process job manager, subscriber management, HexStrike recon subprocess orchestration, event streaming.
- Modify `src/g2_approval.py`: add restore helpers for pending approvals and grants.
- Modify `src/g2_surface.py`: accept active job summaries and render `JOB` surface items above normal actions.
- Modify `src/bridge_server.py`: wire app-level state/job manager, implement `g2.session.resume`, persist approvals/grants, route approved recon to job manager.
- Modify `app/src/config.ts`: persist `clientSessionId` and `lastSeenEventId`.
- Modify `app/src/main.ts`: send `g2.session.resume`, record event ids, handle restored job snapshots.
- Modify `app/src/surface.ts`: normalize optional job items without breaking old surfaces.
- Create tests `tests/test_g2_state.py`, `tests/test_g2_jobs.py`.
- Extend existing Python/Node tests for protocol and config migration.

## Task 1: SQLite State Store

**Files:**
- Create: `src/g2_state.py`
- Test: `tests/test_g2_state.py`

- [x] Write failing tests for session resume, event replay, approval/grant persistence, and job state transitions.
- [x] Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_state`
- [x] Implement `G2StateStore` with schema creation and thread-safe sqlite access.
- [x] Re-run the tests and confirm they pass.

## Task 2: Approval Restore Hooks

**Files:**
- Modify: `src/g2_approval.py`
- Test: `tests/test_g2_approval.py`

- [x] Write failing tests for restoring a pending approval and restoring an unexpired session grant.
- [x] Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_approval`
- [x] Add `restore_pending()` and `restore_grant()` helpers.
- [x] Re-run the tests and confirm they pass.

## Task 3: Job Manager

**Files:**
- Create: `src/g2_jobs.py`
- Test: `tests/test_g2_jobs.py`

- [x] Write failing tests that a recon job emits events, persists output, marks success/failure, and prevents duplicate active jobs for the same session/workflow/target.
- [x] Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_jobs`
- [x] Implement `G2JobManager` around `HexStrikeRunner.build_plan()` and async subprocess streaming.
- [x] Re-run the tests and confirm they pass.

## Task 4: Bridge Session Resume Protocol

**Files:**
- Modify: `src/bridge_server.py`
- Test: `tests/test_bridge_g2_protocol.py`

- [x] Write failing protocol tests for `g2.session.resume`, event replay, restored pending approvals, and active job visibility.
- [x] Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_bridge_g2_protocol`
- [x] Add store/job manager injection to `BridgeConnection` and implement `g2.session.resume`.
- [x] Persist target/scope, approvals, grants, and completion events.
- [x] Re-run the tests and confirm they pass.

## Task 5: Surface Job Items

**Files:**
- Modify: `src/g2_surface.py`
- Test: `tests/test_g2_surface.py`

- [x] Write failing tests for active and completed job surface items.
- [x] Run: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_surface`
- [x] Add optional `jobs` input to `build_default_surface()` and render urgent `JOB` items.
- [x] Re-run the tests and confirm they pass.

## Task 6: App Resume State

**Files:**
- Modify: `app/src/config.ts`
- Modify: `app/src/main.ts`
- Modify: `app/src/surface.ts`
- Test: `app/test/config.test.mjs`, `app/test/surface.test.mjs`

- [x] Write failing tests for `clientSessionId`/`lastSeenEventId` config migration and restored job item normalization.
- [x] Run: `npm test` from `app/`.
- [x] Implement stable `clientSessionId`, `lastSeenEventId` storage, `HermesBridgeClient.resumeSession()`, and event id recording.
- [x] Re-run `npm test` and confirm it passes.

## Task 7: Integration And Deployment

**Files:**
- Modify: `README.md`
- Deploy: `/home/titagram/hermes-g2-bridge`

- [x] Run full Python tests: `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_approval tests.test_g2_hexstrike tests.test_g2_state tests.test_g2_jobs tests.test_g2_surface tests.test_bridge_g2_protocol tests.test_bridge_stt`
- [x] Run app tests and build: `npm test && npm run build` in `app/`.
- [x] Deploy `src/` to the server and restart `hermes-glass-bridge`.
- [x] Probe `g2.session.resume`, start `hex_recon`, disconnect, reconnect, confirm active job recovery.
- [x] Commit implementation.

## Addendum: Hermes Model Selector

**Goal:** Add a G2-accessible model selector for Hermes models exposed by the
Hermes `/model` command, so the user can switch model without speaking or
opening the mobile app.

**Design notes:**
- The bridge should expose semantic model data, not UI layout. Candidate API:
  `g2.models.list`, `g2.models.get`, and `g2.models.set`.
- The bridge should discover the available Hermes models using the same
  behavior Hermes exposes through `/model`, then normalize them into compact
  G2 rows with current/active model marked.
- The G2 app should render a `MODEL` data/action item in the server-driven
  surface and a paginated model picker on the glasses.
- Selection must be possible with scroll + press only, with double press/back
  preserving the current model.
- The active model should be persisted per connection profile/session, because
  people can administer multiple Hermes instances from the same G2 app.
- The mobile UI should expose the same active model state as a safer fallback
  when the model list is long or names are hard to read on glasses.

**Implementation tasks:**
- [ ] Research the Hermes API/CLI path behind `/model` on the server and define
  a bridge adapter that does not depend on brittle text parsing if a structured
  API is available.
- [ ] Add bridge tests for listing models, current model, switching model, and
  failure handling when Hermes does not expose model switching.
- [ ] Add surface/model-picker tests for G2 row formatting and pagination.
- [ ] Add app-side handling for `MODEL` item selection and model commit.
- [ ] Persist selected model per profile/session and include it in reconnect
  recovery.
