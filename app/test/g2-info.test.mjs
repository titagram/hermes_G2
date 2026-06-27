import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_G2_INFO,
  formatModelRow,
  normalizeG2Info,
} from '../dist-test/g2_info.js'

test('normalizes g2 info with model families and report link', () => {
  const info = normalizeG2Info({
    server: { name: 'hermes-glass', version: '1.0.5', protocol: 3 },
    reports: { current: { label: 'Reports', url: 'https://reports.example/current/', source: 'bridge' } },
    models: {
      llm: {
        current: 'gemma4:local',
        canSet: true,
        source: '/models',
        available: [
          { id: 'gemma4:local', label: 'Gemma 4', active: true },
          { id: 'qwen-coder', label: 'Qwen Coder', active: false },
        ],
      },
      stt: { provider: 'local', current: 'tiny', canSet: false, source: 'bridge', available: [] },
      tts: { provider: null, current: null, canSet: false, source: null, available: [] },
    },
  })

  assert.equal(info.server.version, '1.0.5')
  assert.equal(info.reports.current?.url, 'https://reports.example/current/')
  assert.equal(info.models.llm.available.length, 2)
  assert.equal(formatModelRow(info.models.llm.available[0]), 'Gemma 4 current')
})

test('falls back to safe empty g2 info', () => {
  const info = normalizeG2Info(null)

  assert.deepEqual(info, DEFAULT_G2_INFO)
})
