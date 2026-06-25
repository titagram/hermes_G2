import json
import unittest

from src.bridge_server import BridgeConnection


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_str(self, value):
        self.sent.append(json.loads(value))


class FakeHermes:
    stt_model = "whisper-1"
    stt_provider = "local"
    local_stt_model = "tiny"

    def __init__(self):
        self.messages = []

    async def chat_stream(self, message, session_id=None):
        self.messages.append(message)
        yield (None, "ok", "stop")


class BridgeG2ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_surface_get_returns_semantic_items(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({"method": "g2.surface.get", "params": {}}, "surface-1")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["payload"]["version"], 1)
        self.assertTrue(any(item["id"] == "voice" for item in response["payload"]["items"]))

    async def test_action_run_rejects_unknown_action(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({"method": "g2.action.run", "params": {"id": "missing"}}, "run-1")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], False)
        self.assertEqual(response["error"]["code"], 404)

    async def test_action_run_returns_data_detail(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({"method": "g2.action.run", "params": {"id": "server"}}, "run-data")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["payload"]["state"], "detail")
        self.assertEqual(response["payload"]["item"]["id"], "server")

    async def test_action_run_starts_prompt_action(self):
        ws = FakeWs()
        hermes = FakeHermes()
        conn = BridgeConnection(ws, hermes, "test")

        await conn._handle_request({"method": "g2.action.run", "params": {"id": "mail"}}, "run-mail")

        response = ws.sent[0]
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["payload"]["accepted"], True)

    async def test_bootstrap_status_is_structured(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({"method": "g2.bootstrap.status", "params": {}}, "boot-1")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["payload"]["plugin"], "hermes-g2")
        self.assertIn("installed", response["payload"])

    async def test_unknown_g2_method_returns_error(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({"method": "g2.missing", "params": {}}, "missing-1")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], False)
        self.assertEqual(response["error"]["code"], 404)


if __name__ == "__main__":
    unittest.main()
