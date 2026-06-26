# G2 HexStrike Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first G2 approval and target flow for controlled Hermes HexStrike workflows.

**Architecture:** Add a per-connection approval manager to the bridge, enrich the server-driven G2 surface with HexStrike status, HTB target/report data and pending approvals, then extend the app to render approval option lists and submit `g2.approval.respond`. Mobile setup persists target/scope and sends them to the bridge after connect.

**Tech Stack:** Python `unittest` bridge tests, TypeScript/Vite EvenHub app, Node built-in test runner, existing OpenClaw-style WebSocket protocol.

---

## File Map

- `src/g2_approval.py`: approval request, option and session grant normalization/enforcement.
- `src/g2_surface.py`: HexStrike/HTB data items, recon action, pending approval item and target context helpers.
- `src/bridge_server.py`: `g2.target.get`, `g2.target.set`, `g2.approval.list`, `g2.approval.respond`, recon approval creation and grant reuse.
- `tests/test_g2_approval.py`: pure approval manager behavior.
- `tests/test_g2_surface.py`: surface additions and fallback rendering.
- `tests/test_bridge_g2_protocol.py`: protocol request/response behavior.
- `app/src/config.ts`: persisted `hexTarget` and `hexScope`.
- `app/src/surface.ts`: approval payload normalization and option row formatting.
- `app/src/main.ts`: mobile target/scope fields, bridge target sync, approval screen and option handling.
- `app/test/config.test.mjs`, `app/test/surface.test.mjs`: app behavior tests.
- `README.md`: document HexStrike G2 approval workflow.

## Task 1: Approval Manager

- [ ] Add failing tests in `tests/test_g2_approval.py` for creating a recon approval, returning detail without resolving, denying, approving once and approving session with risk ceiling.
- [ ] Run `PYTHONPATH=. /tmp/hermes-g2-test-venv/bin/python -m unittest tests.test_g2_approval` and confirm import/test failure.
- [ ] Create `src/g2_approval.py` with `ApprovalManager`, `ApprovalRequest`, `ApprovalOption`, `TargetContext` and risk comparison helpers.
- [ ] Re-run the test and confirm pass.

## Task 2: Bridge Surface And Target Protocol

- [ ] Extend `tests/test_g2_surface.py` for `RECON`, `HEX`, `HTB` and `approval:<id>` items.
- [ ] Extend `tests/test_bridge_g2_protocol.py` for `g2.target.set`, `g2.approval.list`, `RECON` returning approval, `DETAIL` returning detail and `ONCE` starting a prompt.
- [ ] Run bridge tests and confirm failure.
- [ ] Update `src/g2_surface.py` and `src/bridge_server.py` to satisfy the tests.
- [ ] Re-run bridge tests and confirm pass.

## Task 3: App Approval UI And Target Config

- [ ] Extend `app/test/config.test.mjs` for persisted `hexTarget` and `hexScope`.
- [ ] Extend `app/test/surface.test.mjs` for approval normalization and option row formatting.
- [ ] Run `npm test` and confirm failure.
- [ ] Update `app/src/config.ts`, `app/src/surface.ts` and `app/src/main.ts` for mobile target fields, target sync and approval option list.
- [ ] Re-run `npm test` and confirm pass.

## Task 4: Build, Package, Remote Deploy, Verify

- [ ] Run `npm run build`.
- [ ] Run `npx evenhub pack app.json dist -o HermesGlass.ehpk`.
- [ ] Run Python bridge tests.
- [ ] Deploy bridge files to `/home/titagram/hermes-g2-bridge`, restart the user service, and probe `wss://titagram.tail005130.ts.net:8448/ws`.
- [ ] Run EvenHub simulator for home, approval detail and approve once path.

## Self-Review

- Spec coverage: target setup, surface items, approval options, session grants, G2 controls and verification are covered by tasks 1-4.
- Placeholder scan: no TBD/TODO placeholders are present.
- Type consistency: protocol names use `g2.target.*` and `g2.approval.*` throughout.
