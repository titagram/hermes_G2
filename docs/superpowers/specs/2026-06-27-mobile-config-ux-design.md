# Mobile Config UX Design

## Goal

Make the EvenHub mobile configuration screen safer, clearer, and less technical. The current screen works, but it exposes implementation details too directly and puts too many actions at the same visual priority.

## Scope

This design covers the phone-side WebView UI inside EvenHub, not the G2 glasses display.

## STT Model

The `STT model` field should not be a free text field by default.

Default behavior:

- show a dropdown with known options;
- keep `whisper-1` as the default Hermes-compatible option;
- if the bridge reports local STT, show the effective local model as read-only context;
- move custom text entry into an `Advanced` section as `Custom model`.

The UI should make clear that local faster-whisper model selection is controlled by the bridge server configuration, not by the phone field.

## Voice Timeout

Rename `Recording seconds` to `Voice timeout`.

Tooltip copy:

> Maximum time the glasses microphone records before the app automatically stops, transcribes, and sends the voice input.

Default remains 15 seconds. The allowed range remains 3-60 seconds.

## Help Tooltips

Important fields should have a small `?` help affordance that works on tap, not hover.

Fields that need help:

- Bridge URL;
- Token;
- STT model;
- Voice timeout;
- Input source;
- HexStrike target;
- HexStrike scope;
- Profile selector;
- Test Bridge;
- Send Test Prompt.

Tooltip text must be short, practical, and written for a non-developer using glasses in the field.

## Button Organization

The current button row should be reorganized.

Primary action:

- `Save & Connect` stays visible and visually primary.

Profile management:

- `New Profile`;
- `Save Profile`;
- `Delete Profile`.

These move under a collapsible `Manage profile` section.

Diagnostics:

- `Test Bridge`;
- `Send Test Prompt`.

These move under a collapsible `Advanced` or `Diagnostics` section.

## Status Summary

Add a compact status summary near the top of the screen:

- active profile;
- bridge connection state;
- STT route/provider if known;
- current HexStrike target.

This should let the user understand whether the app is ready without reading every field.

## Design Direction

The phone UI should feel native to EvenHub:

- restrained white/dark surface;
- Even yellow only as accent;
- no glasses-display green in the phone UI;
- dense but readable operational layout;
- no decorative cards or marketing-style sections.

## Testing

- Unit tests for config normalization when `sttModel` comes from dropdown or custom entry.
- Manual mobile test for tooltip tap behavior.
- Manual mobile test for collapsed/expanded sections.
- Regression test that existing saved profiles still load.
