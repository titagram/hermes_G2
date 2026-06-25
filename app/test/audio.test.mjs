import test from 'node:test'
import assert from 'node:assert/strict'

import { createPcm16Wav, mergePcmChunks, readTranscriptPayload } from '../dist-test/audio.js'

test('merges PCM chunks without sharing mutable input buffers', () => {
  const first = new Uint8Array([1, 2])
  const second = new Uint8Array([3])
  const merged = mergePcmChunks([first, second])
  first[0] = 9

  assert.deepEqual([...merged], [1, 2, 3])
})

test('wraps PCM16 mono data in a WAV container', () => {
  const wav = createPcm16Wav(new Uint8Array([1, 0, 2, 0]), 16000)
  const bytes = new Uint8Array(wav)
  const text = new TextDecoder('ascii').decode(bytes)

  assert.equal(text.slice(0, 4), 'RIFF')
  assert.equal(text.slice(8, 12), 'WAVE')
  assert.equal(text.slice(12, 16), 'fmt ')
  assert.equal(text.slice(36, 40), 'data')
  assert.equal(bytes.length, 48)
  assert.deepEqual([...bytes.slice(44)], [1, 0, 2, 0])
})

test('detects old bridge audio transcription acknowledgements', () => {
  assert.throws(
    () => readTranscriptPayload({ ok: true }),
    /does not support audio\.transcribe/,
  )
})
