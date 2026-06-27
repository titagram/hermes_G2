# G2 Display UX Design

## Goal

Move the glasses experience from "chat on a tiny screen" to an operational console for Hermes. The display should show what matters now: connection health, current target, active approvals, running jobs, voice state, and concise results.

## Constraints

The Even Realities G2 display is a 576x288 px monochrome green canvas with:

- no CSS, flexbox, font size, bold, italic, or text alignment;
- one built-in LVGL font with automatic wrapping;
- max 12 containers per page;
- max 8 text/list containers and 4 image containers;
- exactly one event-capture container per page;
- list containers that scroll natively but require full page rebuild to change content;
- text containers that can update quickly with `textContainerUpgrade`.

The first implementation should prefer text/list containers over images. Images are useful later for tiny static icons, but they cost more over BLE and add more failure modes.

## UX Principles

- The first line should answer: connected, agent state, target, and urgent state.
- The user should not need to read logs while walking or testing.
- Urgent items move to the top: approvals, active jobs, alerts.
- Every screen has one primary action and one clear escape.
- Long content is summarized first, then paginated.
- `rebuildPageContainer` is reserved for screen/state changes; `textContainerUpgrade` is used for live job/chat/status updates.

## Screens

### Home Dashboard

Purpose: fast orientation and action selection.

Layout:

- top status text container, around 36 px high;
- native list container for actions/data, around 212 px high;
- bottom hint/status text container, around 40 px high.

Example status:

```text
HERMES OK | HEX OK | 192.168.1.1
```

Example list order:

```text
APPROVAL Quick recon
JOB RECON running
VOICE press to talk
RECON 192.168.1.1
SERVER load 0.42 ram 31%
MAIL important unread
```

Urgency ordering:

1. pending approvals;
2. running jobs;
3. alerts;
4. voice;
5. target actions;
6. data cards;
7. low-priority shortcuts.

### Approval View

Purpose: make a decision, not read a chat.

Layout: text container with compact approval summary and option list.

Example:

```text
APPROVAL LOW
Quick recon
192.168.1.1

Run bounded HexStrike recon

> ONCE
  SESSION LOW 30m
  DENY
  DETAIL
```

Rules:

- low/medium approvals can show actionable options on glasses;
- high approvals show `PHONE`, `DETAIL`, `DENY`;
- choosing `PHONE` displays `Confirm on phone` and does not create a grant;
- double press returns home and does not approve or deny.

### Job View

Purpose: recover and monitor a long-running scan.

Layout: text container updated in-place.

Example:

```text
RECON 192.168.1.1
TCP SCAN
━━━━━━──── 60%

Host up
Scanning top ports
Report pending
```

States:

- `QUEUED`;
- `DISCOVERY`;
- `TCP SCAN`;
- `REPORT`;
- `DONE`;
- `FAILED`;
- `LOST`.

The bridge should send structured job status when possible. Until then, the app may derive coarse status from streamed wrapper lines.

The job screen shows the last few useful lines, not the full stdout log. Full logs remain in the report or detail page.

### Result View

Purpose: show completion outcome and next step.

Example:

```text
RECON DONE
192.168.1.1

Live host found
Open ports: none detected

REPORT READY
```

If report URL exists, show a short `REPORT READY` line on glasses and the full URL/status on the phone UI. The G2 display should not show long URLs unless the user opens detail.

### Voice View

Purpose: make voice state unmistakable.

Examples:

```text
LISTENING
Speak now

tap/ring: stop
```

```text
TRANSCRIBING
Please wait
```

```text
STT ERROR
tap/ring: retry
double: back
```

The timeout should be visible as a short countdown or static limit, for example `timeout 15s`.

### Detail View

Purpose: read more without breaking the operational flow.

Rules:

- paginate at roughly 220-300 chars for comfort;
- status line shows `Page x/y`;
- tap advances page;
- scroll changes page if supported;
- double press returns home.

### Alert View

Purpose: show server/security events that are more important than regular chat.

Example:

```text
ALERT HIGH
Server CPU 96%

tap: detail
double: dismiss
```

Alerts should eventually be server-driven surface items with priority above normal actions.

## Navigation

Preferred controls:

- press/tap: confirm, open, advance, or stop voice;
- scroll: move selection or page;
- double press: back from subviews, exit from home/config;
- long press left temple: start voice when available;
- high-risk approval: phone confirmation only.

No destructive operation should be attached to double press.

## Data Contract Extensions

The surface contract should eventually add optional fields:

```json
{
  "layout": "dashboard|approval|job|detail|alert",
  "urgency": "normal|warning|critical",
  "job": {
    "id": "job_...",
    "state": "running",
    "phase": "tcp_scan",
    "progress": 60,
    "reportUrl": "https://..."
  }
}
```

The app must continue to render older surfaces without these fields.

## Container Strategy

Start with three reusable page templates:

1. `dashboard-list`: status text + native list + bottom hint.
2. `text-status`: body text + bottom hint, updated with `textContainerUpgrade`.
3. `decision`: approval summary + option list rendered as text first, native list later if stable.

Do not introduce image containers in the first pass. Text gives faster feedback and less BLE pressure.

## Integration With Recovery

The G2 display UX depends on the session recovery design:

- active jobs should appear on the home dashboard after reconnect;
- job view should replay recent output and current phase;
- pending approvals should reappear on top;
- completed jobs should show `REPORT READY`;
- lost jobs should show `JOB LOST` with the last known report/log path if available.

## Testing

- Simulator screenshots for home, approval, job running, job done, voice listening, and error states.
- Hardware test for flicker during job output updates.
- Hardware test for list selection with ring and temples.
- Canvas-pixel sanity checks: nonblank display, no overlapping containers, bottom hint visible.
- Regression tests for formatting short rows under 64 chars and paginating detail text.
