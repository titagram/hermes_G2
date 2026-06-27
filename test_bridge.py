#!/usr/bin/env python3
"""Test client for the HermesGlass bridge server using native websockets."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import sys

import websockets


async def request(ws, msg_id, method, params=None, timeout=5):
    await ws.send(json.dumps({
        'type': 'req',
        'id': msg_id,
        'method': method,
        'params': params or {},
    }))
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


def require(condition, message):
    if not condition:
        raise AssertionError(message)

async def test(args):
    async with websockets.connect(args.url, max_size=2**22) as ws:
        # Handshake
        data = await request(ws, 'test-1', 'connect', {
            'minProtocol': 3,
            'maxProtocol': 3,
            'client': {'id': 'test', 'version': '1.0', 'platform': 'web'},
            'role': 'operator',
            'scopes': ['operator.read', 'operator.write'],
        })
        payload = data.get('payload', {})
        require(data.get('ok') is True, 'Handshake failed')
        require(payload.get('protocol') == 3, f'Unexpected protocol: {payload}')
        print(f'Handshake: ok={data.get("ok")}, protocol={payload.get("protocol")}')

        capabilities = await request(ws, 'test-cap', 'bridge.capabilities')
        cap_payload = capabilities.get('payload', {})
        require(capabilities.get('ok') is True, 'bridge.capabilities failed')
        require(
            cap_payload.get('audioTranscribe') is True,
            f'Bridge is old or missing STT capability: {cap_payload}',
        )
        print(f'Capabilities: audioTranscribe={cap_payload.get("audioTranscribe")}, '
              f'sttModel={cap_payload.get("defaultSttModel")}, '
              f'sttProvider={cap_payload.get("sttProvider")}, '
              f'localSttModel={cap_payload.get("localSttModel")}, '
              f'g2Surface={cap_payload.get("g2Surface")}, '
              f'surfaceVersion={cap_payload.get("surfaceVersion")}')

        stt_probe = await request(ws, 'test-stt', 'audio.transcribe')
        require(stt_probe.get('ok') is False, f'audio.transcribe should reject missing audio: {stt_probe}')
        require(stt_probe.get('error', {}).get('code') == 400, f'Unexpected STT validation response: {stt_probe}')
        print('STT route: validation OK')

        if args.audio_file:
            audio_path = Path(args.audio_file)
            audio_b64 = base64.b64encode(audio_path.read_bytes()).decode('ascii')
            stt_result = await request(ws, 'test-stt-audio', 'audio.transcribe', {
                'audioBase64': audio_b64,
                'mimeType': args.audio_mime_type,
                'sttModel': args.stt_model,
            }, timeout=args.stt_timeout)
            require(stt_result.get('ok') is True, f'audio.transcribe failed: {stt_result}')
            transcript = stt_result.get('payload', {}).get('text', '')
            print(f'STT audio: ok, transcript={transcript!r}')

        if args.surface:
            surface = await request(ws, 'test-surface', 'g2.surface.get', timeout=10)
            require(surface.get('ok') is True, f'g2.surface.get failed: {surface}')
            items = surface.get('payload', {}).get('items', [])
            labels = [item.get('label', '?') for item in items if isinstance(item, dict)]
            print(f'G2 surface: {len(items)} items: {", ".join(labels)}')

        if args.run_action:
            action = await request(ws, 'test-action', 'g2.action.run', {
                'id': args.run_action,
                'sessionKey': 'g2-test',
            }, timeout=10)
            require(action.get('ok') is True, f'g2.action.run failed: {action}')
            payload = action.get('payload', {})
            print(f'G2 action {args.run_action!r}: state={payload.get("state")}, '
                  f'accepted={payload.get("accepted")}')

        if args.no_chat:
            print('\n=== DONE ===')
            return

        # Chat
        chat = {
            'type': 'req', 'id': 'test-2', 'method': 'chat.send',
            'params': {'sessionKey': 'g2-test', 'message': args.message}
        }
        await ws.send(json.dumps(chat))
        print(f'Sent: "{args.message}"')

        # Read events
        for _ in range(100):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                for line in raw.strip().split('\n'):
                    if not line.strip(): continue
                    data = json.loads(line)
                    if data.get('type') == 'res':
                        print(f'  res [{data.get("id")}]: ok={data.get("ok")}')
                    elif data.get('type') == 'event':
                        event = data.get('event')
                        payload = data.get('payload', {})
                        if event == 'chat.event':
                            state = payload.get('state')
                            if state == 'delta':
                                c = payload.get('message',{}).get('content','')
                                print(f'  delta: {len(c)} chars')
                            elif state == 'final':
                                c = payload.get('message',{}).get('content','')
                                print(f'  FINAL ({len(c)} chars): {c[:300]}')
                        elif event == 'agent.completion':
                            print(f'  completion: {payload.get("status")}')
                            print('\n=== DONE ===')
                            return
            except asyncio.TimeoutError:
                print('  (timeout)')
                break

def parse_args():
    parser = argparse.ArgumentParser(description='Probe a HermesGlass OpenClaw bridge.')
    parser.add_argument('url', nargs='?', default='ws://127.0.0.1:18790/ws',
                        help='Bridge WebSocket URL')
    parser.add_argument('message', nargs='?', default='Say hello in one short sentence.',
                        help='Chat prompt to send after protocol checks')
    parser.add_argument('--no-chat', action='store_true',
                        help='Only verify handshake, capabilities, and STT route')
    parser.add_argument('--audio-file',
                        help='Optional WAV file to send through audio.transcribe')
    parser.add_argument('--audio-mime-type', default='audio/wav',
                        help='MIME type for --audio-file')
    parser.add_argument('--stt-model', default='whisper-1',
                        help='STT model name to include in the audio.transcribe request')
    parser.add_argument('--stt-timeout', type=float, default=180,
                        help='Timeout for an audio.transcribe probe')
    parser.add_argument('--surface', action='store_true',
                        help='Request g2.surface.get and print semantic item labels')
    parser.add_argument('--run-action',
                        help='Run a semantic G2 action by id before the chat probe')
    return parser.parse_args()


if __name__ == '__main__':
    try:
        asyncio.run(test(parse_args()))
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
