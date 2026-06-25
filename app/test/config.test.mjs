import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CONFIG_STORAGE_KEY,
  DEFAULT_CONFIG,
  activeProfile,
  deleteProfile,
  isInputAllowed,
  normalizeAppConfig,
  parseStoredConfig,
  serializeAppConfig,
  upsertProfile,
} from '../dist-test/config.js'

test('normalizes complete mobile configuration values', () => {
  const config = normalizeAppConfig({
    bridgeUrl: ' ws://example.test:8448/ws ',
    sttModel: ' faster-whisper ',
    maxRecordingMs: 90000,
    inputMode: 'ring',
  })

  assert.equal(config.bridgeUrl, 'ws://example.test:8448/ws')
  assert.equal(config.sttModel, 'faster-whisper')
  assert.equal(config.maxRecordingMs, 60000)
  assert.equal(config.inputMode, 'ring')
})

test('falls back to defaults for invalid configuration', () => {
  const config = normalizeAppConfig({
    bridgeUrl: 'https://not-websocket.example',
    sttModel: '',
    maxRecordingMs: 100,
    inputMode: 'invalid',
  })

  assert.deepEqual(config, DEFAULT_CONFIG)
})

test('round-trips stored configuration JSON', () => {
  const serialized = serializeAppConfig({
    bridgeUrl: 'wss://bridge.example/ws',
    sttModel: 'whisper-large-v3',
    maxRecordingMs: 12000,
    inputMode: 'temples',
  })

  assert.equal(CONFIG_STORAGE_KEY, 'hermesglass_config_v2')
  const parsed = parseStoredConfig(serialized)
  assert.equal(parsed.bridgeUrl, 'wss://bridge.example/ws')
  assert.equal(parsed.sttModel, 'whisper-large-v3')
  assert.equal(parsed.maxRecordingMs, 12000)
  assert.equal(parsed.inputMode, 'temples')
  assert.equal(activeProfile(parsed).url, 'wss://bridge.example/ws')
})

test('filters configured input source modes', () => {
  assert.equal(isInputAllowed('ring', 2), true)
  assert.equal(isInputAllowed('ring', 1), false)
  assert.equal(isInputAllowed('temples', 1), true)
  assert.equal(isInputAllowed('temples', 3), true)
  assert.equal(isInputAllowed('temples', 2), false)
  assert.equal(isInputAllowed('all', 2), true)
  assert.equal(isInputAllowed('all', null), true)
})

test('normalizes multiple connection profiles and trims token values', () => {
  const config = normalizeAppConfig({
    activeProfileId: 'work',
    profiles: [
      { id: 'home', name: ' Home ', url: ' wss://home.example/ws ', token: ' token-home ' },
      { id: 'work', name: 'Work', url: 'wss://work.example/ws', token: ' token-work ' },
      { id: '', name: 'Invalid', url: 'https://not-websocket.example', token: 'bad' },
    ],
  })

  assert.equal(config.profiles.length, 2)
  assert.equal(config.activeProfileId, 'work')
  assert.deepEqual(activeProfile(config), {
    id: 'work',
    name: 'Work',
    url: 'wss://work.example/ws',
    token: 'token-work',
  })
})

test('falls back to default profile for legacy single-url configuration', () => {
  const config = normalizeAppConfig({
    bridgeUrl: 'wss://legacy.example/ws',
  })

  assert.equal(config.profiles.length, 1)
  assert.equal(activeProfile(config).id, 'default')
  assert.equal(activeProfile(config).url, 'wss://legacy.example/ws')
  assert.equal(config.bridgeUrl, 'wss://legacy.example/ws')
})

test('upserts and deletes profiles while preserving an active profile', () => {
  const initial = normalizeAppConfig({
    bridgeUrl: 'wss://home.example/ws',
  })

  const withWork = upsertProfile(initial, {
    id: 'work',
    name: 'Work',
    url: 'wss://work.example/ws',
    token: 'secret',
  }, true)

  assert.equal(withWork.activeProfileId, 'work')
  assert.equal(activeProfile(withWork).url, 'wss://work.example/ws')

  const deleted = deleteProfile(withWork, 'work')
  assert.equal(deleted.activeProfileId, 'default')
  assert.equal(activeProfile(deleted).url, 'wss://home.example/ws')
})
