#!/usr/bin/env python3
"""Test client for the HermesGlass bridge server using native websockets."""
import asyncio, json, sys, websockets

async def test():
    url = sys.argv[1] if len(sys.argv) > 1 else 'ws://127.0.0.1:18790'
    msg_text = sys.argv[2] if len(sys.argv) > 2 else 'Say hello in one short sentence.'

    async with websockets.connect(url, max_size=2**20) as ws:
        # Handshake
        handshake = {
            'type': 'req', 'id': 'test-1', 'method': 'connect',
            'params': {'minProtocol': 3, 'maxProtocol': 3,
                'client': {'id': 'test', 'version': '1.0', 'platform': 'web'},
                'role': 'operator', 'scopes': ['operator.read', 'operator.write']}
        }
        await ws.send(json.dumps(handshake))
        resp = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(resp)
        print(f'Handshake: ok={data.get("ok")}, protocol={data.get("payload",{}).get("protocol")}')

        # Chat
        chat = {
            'type': 'req', 'id': 'test-2', 'method': 'chat.send',
            'params': {'sessionKey': 'g2-test', 'message': msg_text}
        }
        await ws.send(json.dumps(chat))
        print(f'Sent: "{msg_text}"')

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

if __name__ == '__main__':
    asyncio.run(test())