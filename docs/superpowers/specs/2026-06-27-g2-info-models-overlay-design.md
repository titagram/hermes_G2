# G2 Info, Models, and Overlay UX Design

## Goal

Make HermesGlass easier to configure from EvenHub and richer on G2 without
turning the glasses app into a hard-coded Hermes client. The bridge should
expose structured server information, available models, and capability metadata;
the phone app and G2 renderer decide how to present those fields.

This design covers:

- a structured `g2.info` contract;
- discovery of available LLM, STT, and future TTS/voice models;
- a safer mobile configuration layout with collapsed sections;
- a G2 "layered overlay" display direction for approvals, jobs, alerts, and
  model selection.

## Non-Goals

- Do not remove `bridge.capabilities`; keep it as a backward-compatible flat
  capability response.
- Do not make the phone app infer form controls from `g2.surface`.
- Do not require TTS support in the first implementation. TTS fields exist in
  the contract but can report unavailable state.
- Do not expose tokens or other secrets through `g2.info` or `g2.surface`.

## Server Info Contract

Add `g2.info` as the main structured metadata endpoint for mobile setup and G2
feature discovery.

Example response:

```json
{
  "server": {
    "name": "hermes-glass",
    "version": "1.0.5",
    "protocol": 3
  },
  "capabilities": {
    "surface": true,
    "approvals": true,
    "sessionResume": true,
    "audioTranscribe": true,
    "models": true,
    "tts": false
  },
  "reports": {
    "current": {
      "label": "Current engagement report",
      "url": "https://titagram.tail005130.ts.net:8899/engagements/current/",
      "source": "bridge"
    }
  },
  "models": {
    "llm": {
      "current": "gemma4:local",
      "canSet": true,
      "source": "/models",
      "available": [
        { "id": "gemma4:local", "label": "gemma4:local", "active": true },
        { "id": "qwen-coder", "label": "qwen-coder", "active": false }
      ]
    },
    "stt": {
      "provider": "local",
      "current": "tiny",
      "canSet": false,
      "source": "bridge",
      "available": [
        { "id": "tiny", "label": "tiny", "active": true },
        { "id": "base", "label": "base", "active": false },
        { "id": "small", "label": "small", "active": false }
      ]
    },
    "tts": {
      "provider": null,
      "current": null,
      "canSet": false,
      "source": null,
      "available": []
    }
  }
}
```

The important rule is that model families expose both:

- `current`: the currently selected/effective model;
- `available`: all models discovered from the relevant source, including the
  current model when it is known.

The `reports.current.url` field points to the current engagement report page
exposed by the bridge environment, typically through Tailscale. The phone app
renders it as an external link. The URL must come from bridge configuration or
server-side state, not from a hard-coded phone client constant.

## Model Discovery

### LLM

The bridge should discover LLM models from Hermes' model endpoint. The preferred
source is `/models`; if the deployed Hermes API only exposes the
OpenAI-compatible path, the bridge can try `/v1/models` as a fallback.

The bridge normalizes each returned model into:

```json
{ "id": "model-id", "label": "model-id", "active": false }
```

The active model is marked with `active: true` when it matches the current
Hermes model. If the current model is not present in `/models`, the bridge still
adds it to `available` with `active: true` and `source: "configured"`.

Switching LLM model should use a dedicated semantic method:

```json
{
  "method": "g2.models.set",
  "params": { "family": "llm", "modelId": "gemma4:local" }
}
```

The implementation can initially map this to the same internal behavior used by
Hermes `/model`. If Hermes does not expose a stable programmatic setter yet,
`canSet` must be false and the app must render the list read-only.

### STT

STT model information comes from bridge configuration and runtime provider
state:

- `provider`: `local`, `hermes`, or `auto`;
- `current`: effective local model or Hermes transcription model;
- `available`: server-provided list, not free text by default.

For local STT, the bridge can expose a conservative built-in list such as
`tiny`, `base`, `small`, `medium`, and `large-v3`, plus the configured current
model if it is not already in the list. If runtime switching is not implemented,
`canSet` remains false.

### TTS / Voice

TTS/voice is part of the contract from day one:

- `provider`: string or null;
- `current`: string or null;
- `canSet`: false until the bridge has a supported backend;
- `available`: empty until discovery exists.

This keeps the mobile UI and future G2 model picker compatible with voice output
without promising current functionality.

## Mobile EvenHub UX

The phone-side configuration screen should default to collapsed sections:

1. `Profile`
   - Profile
   - Profile name
   - Bridge WebSocket URL
   - Token

2. `Input`
   - STT model
   - Recording seconds
   - Input source

3. `Target`
   - HexStrike target
   - HexStrike scope
   - Report page link

4. `Models`
   - Hermes LLM model
   - STT model summary
   - TTS/voice model summary when available

5. `Controls`
   - New Profile
   - Save Profile
   - Delete Profile
   - Save and Connect
   - Test Bridge
   - Send Test Prompt

All sections should be closed by default. The tooltip panel remains below the
sections, where it is today. Tapping any field help button updates that single
panel instead of creating inline help text under each input.

Model fields should prefer dropdowns populated from `g2.info.models.*.available`.
Free text remains an advanced fallback only when the server cannot expose a
model list.

The `Target` section should include an `Open Reports` link when
`g2.info.reports.current.url` is present. It opens the Tailscale report page
for the current engagement, for example the existing
`https://titagram.tail005130.ts.net:8899/engagements/current/` endpoint. If the
bridge does not report a URL, the link is hidden.

## G2 Overlay UX Direction

Use the selected "layered overlay" direction for the glasses. On G2 this is a
simulated overlay, not a CSS layer:

- the base dashboard keeps a compact status line and bottom hint;
- urgent overlays rebuild the page with a central decision/detail area;
- containers are declared so the overlay content visually appears above the base
  context where firmware rendering allows it;
- double press returns to the dashboard;
- press confirms or opens;
- scroll moves selection or pages content.

Initial overlay targets:

- approval overlay;
- active job overlay;
- alert overlay;
- model picker overlay.

The model picker overlay should show the current LLM model and discovered
available models from `/models`. It should be reachable without voice.

## Data Flow

On connect:

1. phone app opens WebSocket;
2. app sends `bridge.capabilities` for backward compatibility;
3. app sends `g2.info`;
4. app stores `g2.info` in transient runtime state;
5. app populates mobile dropdowns from `models.*.available`;
6. app resumes session with `g2.session.resume`;
7. app fetches and renders `g2.surface.get`.

When the model list changes or the user reconnects, the app refreshes `g2.info`.
The bridge may cache `/models` briefly, but should not require restarting the
phone app to observe a new model.

## Error Handling

- If `/models` fails, `g2.info` still succeeds with `available` containing at
  least the configured current model when known.
- If model switching fails, return a normal protocol error and keep the previous
  current model.
- If TTS is unsupported, report `canSet: false` and `available: []`.
- If old bridges do not implement `g2.info`, the app falls back to current
  `bridge.capabilities` behavior and keeps text input where no list exists.

## Testing

Server tests:

- `g2.info` returns LLM, STT, and TTS model families;
- LLM `available` is populated from `/models`;
- current LLM is included and marked active even when missing from `/models`;
- `/models` failure falls back without failing `g2.info`;
- `g2.models.set` updates current model or returns a clear unsupported error.

App tests:

- mobile sections render closed by default;
- tooltip panel remains outside the collapsed sections and updates from `?`;
- model dropdowns use `g2.info.models.*.available`;
- report link renders only when `g2.info.reports.current.url` is present;
- old bridge fallback preserves existing manual STT field behavior;
- G2 model picker formats rows under firmware list limits.

Simulator or hardware checks:

- dashboard overlay is legible on 576x288;
- approval overlay still supports approve once, session, detail, deny;
- model picker can be navigated with scroll and selected with press;
- double press returns to dashboard without changing model.
