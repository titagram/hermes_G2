import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DASHBOARD_DIMENSIONS,
  buildApprovalDecisionText,
  buildDashboardFallbackText,
  buildDashboardView,
  buildStatusPageText,
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
  assert.deepEqual(view.rows, [
    'SERVER LOAD 0.12 RAM 39%',
    'RECON 192.168.1.1',
    'VOICE press to talk',
  ])
  assert.equal(view.hint, '2/3 RECON | press select | double exit')
})

test('dashboard dimensions preserve header list and hint bands', () => {
  assert.deepEqual(DASHBOARD_DIMENSIONS, {
    headerHeight: 36,
    listY: 36,
    listHeight: 212,
    hintY: 248,
    hintHeight: 40,
  })
})

test('dashboard fallback text keeps the same hierarchy as native layout', () => {
  const view = {
    header: 'HERMES OK | IDLE',
    rows: ['SERVER ok', 'RECON 192.168.1.1'],
    hint: '1/2 SERVER | press select | double exit',
  }

  assert.equal(
    buildDashboardFallbackText(view, 0),
    'HERMES OK | IDLE\n\n> SERVER ok\n  RECON 192.168.1.1\n\n1/2 SERVER | press select | double exit'
  )
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
  assert.match(text, /Run bounded HexStrike recon/)
  assert.match(text, /> SESSION LOW 30m low/)
})

test('cleans markdown and urls for the firmware font', () => {
  assert.equal(cleanForG2('**Done** see https://example.test/x and `code`'), 'Done see [link] and code')
})

test('builds voice status text with timeout context', () => {
  assert.equal(buildVoiceStatusText('listening', 15), 'LISTENING\nSpeak now\n\ntimeout 15s')
  assert.equal(
    buildVoiceStatusText('stt-error', 15, 'Hermes STT API error 404'),
    'STT ERROR\nHermes STT API error 404\n\ntap/ring retry'
  )
})

test('builds clipped status pages for simple app states', () => {
  assert.equal(
    buildStatusPageText('connecting', ['Hermes bridge', 'wss://example.test/ws']),
    'CONNECTING\nHermes bridge\n[link]'
  )
})
