# G2 HexStrike Approval Design

## Goal

Add a G2-first approval and target flow for Hermes HexStrike workflows. The glasses must be able to receive approval requests in real time, inspect details, approve once, approve for a bounded workflow/session, or deny without using voice.

## Scope

This design covers the first controlled HexStrike workflow path through the Hermes G2 bridge. It does not try to expose all HexStrike MCP tools directly to the glasses and does not make the glasses talk to HexStrike. Chat and voice still route through Hermes; the first G2 `RECON` action uses a bounded server-side HexStrike worker so the glasses receive deterministic progress and do not wait on invisible Hermes-side tool approvals.

## Architecture

The bridge owns a small approval bus per WebSocket connection. G2 actions that require consent create structured approval requests. The G2 app renders pending approvals as high-priority surface items and sends explicit responses through `g2.approval.respond`.

```text
G2 app
  -> g2.target.set / g2.surface.get / g2.action.run
  -> bridge approval bus
  -> bounded HexStrike runner
  -> run-lan-scan.sh
  -> Kali container / HexStrike server
  -> streamed G2 chat.event progress + report URL
```

## Target And Scope

Targets are configured from the mobile EvenHub UI, not typed on glasses by default.

The app persists:

- `hexTarget`: current target, for example `10.129.22.74`.
- `hexScope`: short authorization/scope text.

After connecting, the app sends:

```json
{
  "method": "g2.target.set",
  "params": {
    "target": "10.129.22.74",
    "scope": "HTB authorized machine"
  }
}
```

If no mobile target is set, no scan workflow may start. Targets are normalized for common G2/mobile entry mistakes such as `192.168.1.0 /24` or `192.168.1.0 \24`.

The direct G2 worker validates targets against `G2_HEXSTRIKE_ALLOWED_CIDRS`; defaults allow private lab ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). Public CIDRs such as `192.169.1.0/24` are rejected unless explicitly allowlisted on the server.

## Surface Items

The bridge adds these optional items when HexStrike is available:

- `HEX`: data item with HexStrike health, essential tools, command count, CPU and memory.
- `HTB`: data item with current target, engagement status, observation/evidence counts and report URL.
- `RECON`: action item for a controlled HexStrike recon workflow against the current target.
- `approval:<id>`: high-priority action item when an approval is pending.

The G2 home remains a server-driven list. The app should not hard-code HexStrike layout beyond rendering `approval` responses.

## Approval Contract

`g2.action.run` may return:

```json
{
  "state": "approval",
  "approval": {
    "id": "appr_123",
    "title": "Quick recon",
    "target": "10.129.22.74",
    "workflow": "hexstrike-recon",
    "risk": "low",
    "reason": "Run non-destructive service reconnaissance.",
    "detail": "HermesGlass will run a bounded HexStrike quick recon wrapper and only read service metadata.",
    "options": [
      {"id": "once", "label": "ONCE", "kind": "approve_once"},
      {"id": "session-low", "label": "SESSION LOW", "kind": "approve_session", "riskCeiling": "low", "ttlMinutes": 30},
      {"id": "session-medium", "label": "SESSION MED", "kind": "approve_session", "riskCeiling": "medium", "ttlMinutes": 15},
      {"id": "deny", "label": "DENY", "kind": "deny"},
      {"id": "detail", "label": "DETAIL", "kind": "detail"}
    ]
  }
}
```

The app renders the approval title and target, then a native list of options.

`g2.approval.respond` accepts:

```json
{
  "id": "appr_123",
  "optionId": "session-low",
  "sessionKey": "g2-hermes"
}
```

Response shapes:

- `{"state":"running","accepted":true}` when an approval starts the workflow.
- `{"state":"denied","accepted":false}` when denied.
- `{"state":"detail","item":{...}}` for `DETAIL`.
- Error `404` for unknown or expired approvals.

## Session Grants

`approve_session` creates a bounded grant:

- same target
- same workflow
- same G2 bridge connection
- risk not above `riskCeiling`
- TTL from the selected option

The bridge must not show session options that it is not willing to enforce. If a future operation changes target, workflow, or exceeds the risk ceiling, a new approval is required.

## G2 Controls

- Home press: select item.
- Approval option press: choose option.
- Double press: back to home; it does not approve and does not deny.
- `DENY` is a list option, not a double-press shortcut.
- `DETAIL` opens a read-only detail page.

## First Workflow

`RECON` starts a bounded worker on the bridge host after approval or an applicable session grant:

```bash
cd /home/titagram/hexstrike-kali-hermes
./run-lan-scan.sh --targets "<target>" --name "g2-<target-slug>" --profile quick --extra-nmap "--host-timeout 60s --max-retries 2"
```

The bridge streams wrapper output as `chat.event` deltas and sends a final message with the report URL.

## Safety

The first implementation supports `low` and `medium` session grants. No `high` or destructive session grant is offered. Future high-risk approvals must be once-only unless a separate design explicitly expands the model.

## Verification

- Unit tests for target normalization/allowlisting, HexStrike status item fallback, pending approval surface item, approval response outcomes and session grant reuse.
- App tests for approval normalization and option rows.
- Simulator test for approval list rendering and selecting `DETAIL`/`ONCE`.
- Remote probe against `wss://titagram.tail005130.ts.net:8448/ws` after deployment.
