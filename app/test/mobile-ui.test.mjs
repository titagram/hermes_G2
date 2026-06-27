import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  APP_RELEASE_LABEL,
  CONFIG_HELP_TEXT,
  configSection,
  fieldHelp,
  helpButton,
} from '../dist-test/mobile_ui.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const manifest = JSON.parse(readFileSync(join(__dirname, '..', 'app.json'), 'utf8'))

test('mobile UI release label matches Even Hub manifest version', () => {
  assert.equal(manifest.version, '1.0.5')
  assert.equal(APP_RELEASE_LABEL, 'v1.0.5 cyber')
})

test('mobile UI explains ambiguous configuration fields', () => {
  assert.match(fieldHelp('sttModel'), /Hermes STT/i)
  assert.match(fieldHelp('recording'), /3.*60/)
  assert.match(fieldHelp('target'), /CIDR/i)
  assert.match(fieldHelp('inputMode'), /ring/i)
  assert.equal(Object.keys(CONFIG_HELP_TEXT).length >= 7, true)
})

test('mobile UI help button is accessible and keyed by field', () => {
  const button = helpButton('sttModel')

  assert.match(button, /class="help-button"/)
  assert.match(button, /data-help-field="sttModel"/)
  assert.match(button, /aria-label="STT model help"/)
  assert.match(button, />\?</)
})

test('mobile UI renders collapsed config sections by default', () => {
  const html = configSection('Profile', 'Default', '<input id="x">')

  assert.match(html, /<details class="config-section">/)
  assert.doesNotMatch(html, / open>/)
  assert.match(html, /<summary>/)
  assert.match(html, /Default/)
})
