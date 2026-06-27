export const APP_RELEASE_LABEL = 'v1.0.4 cyber'

export const CONFIG_HELP_TEXT = {
  profiles: 'Connection profiles keep URL, token, session cursor and recovery state separate for each Hermes instance.',
  bridgeUrl: 'Use the WebSocket bridge URL exposed through Tailscale, Cloudflare or another secure tunnel.',
  token: 'Leave empty when the bridge does not require a token. Tokens are stored only in the Even Hub local config.',
  sttModel: 'Hermes STT model sent to audio.transcribe. With local STT, the server can still override this through its provider settings.',
  recording: 'Voice capture timeout in seconds. Valid range is 3 to 60; shorter values feel faster on G2.',
  inputMode: 'Choose whether ring, temples, or both can trigger voice recording and action selection.',
  target: 'Authorized HexStrike target, IP or CIDR. Private lab CIDRs are accepted by default; public ranges require server allow-listing.',
  scope: 'Human-readable authorization scope shown in G2 approvals and scan logs.',
} as const

export type ConfigHelpField = keyof typeof CONFIG_HELP_TEXT

const HELP_LABELS: Record<ConfigHelpField, string> = {
  profiles: 'Profile',
  bridgeUrl: 'Bridge URL',
  token: 'Token',
  sttModel: 'STT model',
  recording: 'Recording seconds',
  inputMode: 'Input source',
  target: 'HexStrike target',
  scope: 'HexStrike scope',
}

export function fieldHelp(field: ConfigHelpField): string {
  return CONFIG_HELP_TEXT[field]
}

export function helpButton(field: ConfigHelpField): string {
  const label = HELP_LABELS[field]
  return `<button class="help-button" type="button" data-help-field="${field}" aria-label="${label} help">?</button>`
}

export function fieldLabel(forId: string, text: string, field: ConfigHelpField): string {
  return `<div class="label-row"><label class="field-label" for="${forId}">${text}</label>${helpButton(field)}</div>`
}
