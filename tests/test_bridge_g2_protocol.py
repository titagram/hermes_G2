import json
import asyncio
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


class FakeHexRunner:
    def __init__(self):
        self.targets = []

    def validate_target(self, target):
        return target

    async def stream_recon(self, target):
        self.targets.append(target.target)
        yield "started"
        yield "done"


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

    async def test_target_set_is_reflected_in_surface(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({
            "method": "g2.target.set",
            "params": {"target": "10.129.22.74", "scope": "HTB authorized machine"},
        }, "target-set")
        await conn._handle_request({"method": "g2.surface.get", "params": {}}, "surface-target")

        target_response = ws.sent[-2]
        surface_response = ws.sent[-1]
        self.assertEqual(target_response["payload"]["target"], "10.129.22.74")
        htb = next(item for item in surface_response["payload"]["items"] if item["id"] == "htb")
        self.assertIn("10.129.22.74", htb["summary"])

    async def test_recon_action_returns_approval_request(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({
            "method": "g2.target.set",
            "params": {"target": "10.129.22.74", "scope": "HTB authorized machine"},
        }, "target-set")
        await conn._handle_request({"method": "g2.action.run", "params": {"id": "hex_recon"}}, "recon")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["payload"]["state"], "approval")
        self.assertEqual(response["payload"]["approval"]["target"], "10.129.22.74")
        self.assertIn("session-medium", [option["id"] for option in response["payload"]["approval"]["options"]])

    async def test_approval_detail_and_once_response(self):
        ws = FakeWs()
        hermes = FakeHermes()
        conn = BridgeConnection(ws, hermes, "test")
        runner = FakeHexRunner()
        conn.hex_runner = runner

        await conn._handle_request({
            "method": "g2.target.set",
            "params": {"target": "10.129.22.74", "scope": "HTB authorized machine"},
        }, "target-set")
        await conn._handle_request({"method": "g2.action.run", "params": {"id": "hex_recon"}}, "recon")
        approval = ws.sent[-1]["payload"]["approval"]

        await conn._handle_request({
            "method": "g2.approval.respond",
            "params": {"id": approval["id"], "optionId": "detail"},
        }, "approval-detail")
        detail_response = ws.sent[-1]
        self.assertEqual(detail_response["payload"]["state"], "detail")
        self.assertIn("Quick recon", detail_response["payload"]["item"]["detail"])

        await conn._handle_request({
            "method": "g2.approval.respond",
            "params": {"id": approval["id"], "optionId": "once", "sessionKey": "g2-test"},
        }, "approval-once")
        once_response = ws.sent[-1]
        self.assertEqual(once_response["payload"]["state"], "running")
        self.assertEqual(once_response["payload"]["accepted"], True)
        await asyncio.sleep(0)
        self.assertEqual(hermes.messages, [])
        self.assertEqual(runner.targets, ["10.129.22.74"])

    async def test_session_grant_skips_second_recon_approval(self):
        ws = FakeWs()
        hermes = FakeHermes()
        conn = BridgeConnection(ws, hermes, "test")
        runner = FakeHexRunner()
        conn.hex_runner = runner

        await conn._handle_request({
            "method": "g2.target.set",
            "params": {"target": "10.129.22.74", "scope": "HTB authorized machine"},
        }, "target-set")
        await conn._handle_request({"method": "g2.action.run", "params": {"id": "hex_recon"}}, "recon-1")
        approval = ws.sent[-1]["payload"]["approval"]
        await conn._handle_request({
            "method": "g2.approval.respond",
            "params": {"id": approval["id"], "optionId": "session-low", "sessionKey": "g2-test"},
        }, "approval-session")
        await conn._handle_request({
            "method": "g2.action.run",
            "params": {"id": "hex_recon", "sessionKey": "g2-test"},
        }, "recon-2")

        response = ws.sent[-1]
        self.assertEqual(response["payload"]["state"], "running")
        self.assertNotIn("approval", response["payload"])
        await asyncio.sleep(0)
        self.assertEqual(hermes.messages, [])
        self.assertEqual(runner.targets, ["10.129.22.74", "10.129.22.74"])

    async def test_recon_action_rejects_public_cidr_before_approval(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({
            "method": "g2.target.set",
            "params": {"target": "192.169.1.0 \\24", "scope": "lab"},
        }, "target-set")
        await conn._handle_request({"method": "g2.action.run", "params": {"id": "hex_recon"}}, "recon")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], False)
        self.assertEqual(response["error"]["code"], 400)
        self.assertIn("outside allowed", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
