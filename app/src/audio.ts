export const PCM_SAMPLE_RATE = 16000

export function mergePcmChunks(chunks: Uint8Array[]): Uint8Array {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0)
  const merged = new Uint8Array(totalLength)
  let offset = 0

  for (const chunk of chunks) {
    merged.set(chunk, offset)
    offset += chunk.byteLength
  }

  return merged
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i))
}

export function createPcm16Wav(pcm: Uint8Array, sampleRate = PCM_SAMPLE_RATE): ArrayBuffer {
  const channels = 1
  const bitsPerSample = 16
  const blockAlign = channels * bitsPerSample / 8
  const byteRate = sampleRate * blockAlign
  const buffer = new ArrayBuffer(44 + pcm.byteLength)
  const view = new DataView(buffer)

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + pcm.byteLength, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, channels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, bitsPerSample, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, pcm.byteLength, true)
  new Uint8Array(buffer, 44).set(pcm)

  return buffer
}

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunkSize = 0x8000

  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }

  return btoa(binary)
}

export function readTranscriptPayload(payload: Record<string, unknown>): string {
  const text = payload.text ?? payload.transcript ?? payload.result
  if (typeof text === 'string' && text.trim()) return text.trim()
  if (payload.ok === true) {
    throw new Error('Bridge does not support audio.transcribe yet. Restart the updated HermesGlass bridge.')
  }
  throw new Error('Empty transcript')
}
