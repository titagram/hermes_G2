import test from 'node:test'
import assert from 'node:assert/strict'

import {
  formatApprovalOptionRow,
  formatHomeRow,
  normalizeApproval,
  normalizeSurface,
  paginateDetail,
} from '../dist-test/surface.js'

test('normalizes invalid surface to safe empty defaults', () => {
  const surface = normalizeSurface(null)

  assert.equal(surface.version, 1)
  assert.equal(surface.status.connection, 'unknown')
  assert.deepEqual(surface.items, [])
})

test('normalizes, sorts, and clips surface item labels for G2 rows', () => {
  const surface = normalizeSurface({
    version: 1,
    updatedAt: 123,
    status: { agent: 'idle', connection: 'ok' },
    items: [
      { id: 'daily', type: 'action', label: 'daily briefing', summary: 'ready', priority: 1 },
      { id: 'server', type: 'data', label: 'server', summary: '56C RAM 41%', priority: 10 },
    ],
  })

  assert.equal(surface.items[0].id, 'server')
  assert.equal(formatHomeRow(surface.items[0]), 'SERVER 56C RAM 41%')
  assert.equal(formatHomeRow(surface.items[1]), 'DAILY BRIEFING ready')
})

test('paginates detail text with a fallback summary', () => {
  const pages = paginateDetail({
    id: 'server',
    type: 'data',
    label: 'SERVER',
    summary: 'ok',
    detail: 'A'.repeat(260),
    priority: 0,
  }, 120)

  assert.equal(pages.length, 3)
  assert.equal(pages[0].length, 120)

  const fallback = paginateDetail({
    id: 'mail',
    type: 'action',
    label: 'MAIL',
    summary: '12 unread',
    priority: 0,
  })
  assert.deepEqual(fallback, ['MAIL\n\n12 unread'])
})

test('normalizes approval payload with configurable options', () => {
  const approval = normalizeApproval({
    id: 'appr_123',
    title: 'Quick recon',
    target: '10.129.22.74',
    workflow: 'hexstrike-recon',
    risk: 'low',
    reason: 'Run recon',
    detail: 'Details',
    options: [
      { id: 'once', label: 'ONCE', kind: 'approve_once' },
      { id: 'session-low', label: 'SESSION LOW', kind: 'approve_session', riskCeiling: 'low', ttlMinutes: 30 },
      { id: 'deny', label: 'DENY', kind: 'deny' },
    ],
  })

  assert.equal(approval?.id, 'appr_123')
  assert.equal(approval?.target, '10.129.22.74')
  assert.equal(approval?.options.length, 3)
  assert.equal(approval?.options[1].riskCeiling, 'low')
  assert.equal(formatApprovalOptionRow(approval.options[1]), 'SESSION LOW 30m low')
})

test('rejects invalid approval payloads', () => {
  assert.equal(normalizeApproval(null), null)
  assert.equal(normalizeApproval({ id: '', options: [] }), null)
})
