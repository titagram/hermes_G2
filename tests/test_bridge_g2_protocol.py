import json
import asyncio
import os
import tempfile
import unittest

from src.bridge_server import BridgeConnection, HermesClient, _extract_model_ids
from src.g2_jobs import G2JobManager
from src.g2_state import G2StateStore


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_str(self, value):
        self.sent.append(json.loads(value))


class FakeHermes:
    model = "hermes-agent"
    stt_model = "whisper-1"
    stt_provider = "local"
    local_stt_model = "tiny"
    available_models = ["hermes-agent"]

    def __init__(self):
        self.messages = []
        self.switched_models = []

    async def chat_stream(self, message, session_id=None):
        self.messages.append(message)
        yield (None, "ok", "stop")

    async def list_models(self):
        return list(self.available_models), "/models"

    async def set_model(self, model_id):
        self.switched_models.append(model_id)
        self.model = model_id


class FakeHexRunner:
    def __init__(self):
        self.targets = []

    def build_plan(self, target):
        from src.g2_hexstrike import HexStrikeRunPlan
        return HexStrikeRunPlan(
            target=target,
            name=f"g2-{target.replace('.', '-')}",
            command=["scan", target],
            report_url=f"https://reports.example/{target}/",
        )

    def validate_target(self, target):
        return target

    async def stream_recon(self, target):
        self.targets.append(target.target)
        yield "started"
        yield "done"


class BridgeG2ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        old_health_url = os.environ.get("HEXSTRIKE_HEALTH_URL")
        os.environ["HEXSTRIKE_HEALTH_URL"] = "http://127.0.0.1:1/health"

        def restore_health_url():
            if old_health_url is None:
                os.environ.pop("HEXSTRIKE_HEALTH_URL", None)
            else:
                os.environ["HEXSTRIKE_HEALTH_URL"] = old_health_url

        self.addCleanup(restore_health_url)

    def test_extract_model_ids_supports_ollama_tags(self):
        models = _extract_model_ids({
            "models": [
                {"name": "gemma4:latest"},
                {"model": "qwen3.6:latest"},
                {"id": "hermes-agent"},
                {"name": "gemma4:latest"},
            ],
        })

        self.assertEqual(models, ["gemma4:latest", "qwen3.6:latest", "hermes-agent"])

    async def test_hermes_client_set_model_updates_gateway_config(self):
        calls = []

        async def fake_runner(args):
            calls.append(args)

        hermes = HermesClient(
            "http://127.0.0.1:8642",
            "",
            model="hermes-agent",
            model_switch_config_command=("hermes", "config", "set"),
            model_switch_restart_command=("systemctl", "--user", "restart", "hermes-gateway.service"),
            command_runner=fake_runner,
        )

        await hermes.set_model("gemma4:latest")

        self.assertEqual(calls, [
            ["hermes", "config", "set", "model.default", "gemma4:latest"],
            ["hermes", "config", "set", "model.provider", "custom:Local Ollama"],
            ["hermes", "config", "set", "model.base_url", "http://127.0.0.1:11434/v1"],
            ["hermes", "config", "set", "model.api_mode", "chat_completions"],
            ["hermes", "config", "set", "model.api_key", "ollama"],
            ["systemctl", "--user", "restart", "hermes-gateway.service"],
        ])
        self.assertEqual(hermes.model, "gemma4:latest")

    def test_hermes_client_current_model_reads_gateway_config(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write(
                "model:\n"
                "  default: gpt-5.5\n"
                "  provider: openai-codex\n"
                "  base_url: https://chatgpt.com/backend-api/codex\n"
            )
            config_path = handle.name
        self.addCleanup(lambda: os.path.exists(config_path) and os.unlink(config_path))

        hermes = HermesClient(
            "http://127.0.0.1:8642",
            "",
            model="hermes-agent",
            model_config_path=config_path,
            model_switch_config_command=(),
        )

        self.assertEqual(hermes.current_model(), "gpt-5.5")

    def stateful_conn(self, store, runner=None):
        ws = FakeWs()
        manager = G2JobManager(store, runner=runner or FakeHexRunner())
        return ws, BridgeConnection(ws, FakeHermes(), "test", state_store=store, job_manager=manager), manager

    async def test_surface_get_returns_semantic_items(self):
        ws = FakeWs()
        conn = BridgeConnection(ws, FakeHermes(), "test")

        await conn._handle_request({"method": "g2.surface.get", "params": {}}, "surface-1")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["payload"]["version"], 1)
        self.assertTrue(any(item["id"] == "voice" for item in response["payload"]["items"]))

    async def test_g2_info_returns_models_reports_and_capabilities(self):
        ws = FakeWs()
        hermes = FakeHermes()
        hermes.available_models = ["gemma4:local", "qwen-coder"]
        hermes.model = "gemma4:local"
        conn = BridgeConnection(ws, hermes, "test")

        await conn._handle_request({"method": "g2.info", "params": {}}, "info-1")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        payload = response["payload"]
        self.assertEqual(payload["capabilities"]["models"], True)
        self.assertEqual(payload["models"]["llm"]["current"], "gemma4:local")
        self.assertEqual(
            [item["id"] for item in payload["models"]["llm"]["available"]],
            ["gemma4:local", "qwen-coder"],
        )
        self.assertEqual(payload["models"]["llm"]["available"][0]["active"], True)
        self.assertIn("reports", payload)
        self.assertTrue(payload["reports"]["current"]["url"].startswith("https://"))
        self.assertEqual(payload["models"]["tts"]["available"], [])

    async def test_g2_info_includes_current_model_when_models_endpoint_misses_it(self):
        ws = FakeWs()
        hermes = FakeHermes()
        hermes.available_models = ["qwen-coder"]
        hermes.model = "gemma4:local"
        conn = BridgeConnection(ws, hermes, "test")

        await conn._handle_request({"method": "g2.info", "params": {}}, "info-2")

        llm = ws.sent[-1]["payload"]["models"]["llm"]
        self.assertEqual(llm["current"], "gemma4:local")
        self.assertIn("gemma4:local", [item["id"] for item in llm["available"]])
        self.assertTrue(next(item for item in llm["available"] if item["id"] == "gemma4:local")["active"])

    async def test_g2_models_set_updates_current_llm_model(self):
        ws = FakeWs()
        hermes = FakeHermes()
        hermes.available_models = ["gemma4:local", "qwen-coder"]
        hermes.model = "gemma4:local"
        conn = BridgeConnection(ws, hermes, "test")

        await conn._handle_request({
            "method": "g2.models.set",
            "params": {"family": "llm", "modelId": "qwen-coder"},
        }, "model-set")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(hermes.switched_models, ["qwen-coder"])
        self.assertEqual(hermes.model, "qwen-coder")
        self.assertEqual(response["payload"]["models"]["llm"]["current"], "qwen-coder")

    async def test_g2_models_set_current_model_is_noop_when_not_discovered(self):
        ws = FakeWs()
        hermes = FakeHermes()
        hermes.available_models = ["gemma4:local", "qwen-coder"]
        hermes.model = "gpt-5.5"
        conn = BridgeConnection(ws, hermes, "test")

        await conn._handle_request({
            "method": "g2.models.set",
            "params": {"family": "llm", "modelId": "gpt-5.5"},
        }, "model-set-current")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], True)
        self.assertEqual(hermes.switched_models, [])
        self.assertEqual(response["payload"]["models"]["llm"]["current"], "gpt-5.5")

    async def test_g2_models_set_rejects_unknown_model(self):
        ws = FakeWs()
        hermes = FakeHermes()
        hermes.available_models = ["gemma4:local"]
        conn = BridgeConnection(ws, hermes, "test")

        await conn._handle_request({
            "method": "g2.models.set",
            "params": {"family": "llm", "modelId": "missing"},
        }, "model-missing")

        response = ws.sent[-1]
        self.assertEqual(response["ok"], False)
        self.assertEqual(response["error"]["code"], 404)

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

    async def test_session_resume_restores_target_pending_approval_and_events(self):
        store = G2StateStore(":memory:")
        self.addCleanup(store.close)
        runner = FakeHexRunner()
        ws1, conn1, _manager = self.stateful_conn(store, runner)

        await conn1._handle_request({
            "method": "g2.session.resume",
            "params": {"clientSessionId": "client-1", "profileId": "default"},
        }, "resume-1")
        session = ws1.sent[-1]["payload"]["session"]
        await conn1._handle_request({
            "method": "g2.target.set",
            "params": {"target": "10.129.22.74", "scope": "HTB authorized machine"},
        }, "target-set")
        await conn1._handle_request({"method": "g2.action.run", "params": {"id": "hex_recon"}}, "recon")
        approval = ws1.sent[-1]["payload"]["approval"]
        first_event = store.append_event(session["id"], "chat.event", {"state": "delta", "message": "old"})
        store.append_event(session["id"], "chat.event", {"state": "final", "message": "new"})

        ws2, conn2, _manager2 = self.stateful_conn(store, runner)
        await conn2._handle_request({
            "method": "g2.session.resume",
            "params": {
                "clientSessionId": "client-1",
                "profileId": "default",
                "lastSeenEventId": first_event["eventId"],
            },
        }, "resume-2")

        payload = ws2.sent[-1]["payload"]
        self.assertEqual(payload["session"]["id"], session["id"])
        self.assertEqual(payload["target"]["target"], "10.129.22.74")
        self.assertEqual(payload["pendingApprovals"][0]["id"], approval["id"])
        self.assertEqual([event["type"] for event in payload["missedEvents"]], ["chat.event"])
        self.assertEqual(payload["missedEvents"][0]["payload"]["message"], "new")

    async def test_resume_returns_active_jobs(self):
        store = G2StateStore(":memory:")
        self.addCleanup(store.close)
        session = store.resume_session("client-1", "default")["session"]
        job = store.create_job(
            session["id"],
            workflow="hexstrike-recon",
            target="10.129.22.74",
            state="running",
            command=["scan", "10.129.22.74"],
            report_url="https://reports.example/10.129.22.74/",
        )
        ws, conn, _manager = self.stateful_conn(store)

        await conn._handle_request({
            "method": "g2.session.resume",
            "params": {"clientSessionId": "client-1", "profileId": "default"},
        }, "resume-jobs")

        payload = ws.sent[-1]["payload"]
        self.assertEqual(payload["jobs"][0]["id"], job["id"])
        self.assertEqual(payload["jobs"][0]["state"], "running")

    async def test_surface_after_resume_includes_active_jobs(self):
        store = G2StateStore(":memory:")
        self.addCleanup(store.close)
        session = store.resume_session("client-1", "default")["session"]
        job = store.create_job(
            session["id"],
            workflow="hexstrike-recon",
            target="10.129.22.74",
            state="running",
            command=["scan", "10.129.22.74"],
        )
        ws, conn, _manager = self.stateful_conn(store)

        await conn._handle_request({
            "method": "g2.session.resume",
            "params": {"clientSessionId": "client-1", "profileId": "default"},
        }, "resume")
        await conn._handle_request({"method": "g2.surface.get", "params": {}}, "surface")

        items = ws.sent[-1]["payload"]["items"]
        self.assertTrue(any(item["id"] == f"job:{job['id']}" for item in items))

    async def test_restored_session_grant_skips_reconnect_approval(self):
        store = G2StateStore(":memory:")
        self.addCleanup(store.close)
        runner = FakeHexRunner()
        ws1, conn1, manager = self.stateful_conn(store, runner)

        await conn1._handle_request({
            "method": "g2.session.resume",
            "params": {"clientSessionId": "client-1", "profileId": "default"},
        }, "resume-1")
        await conn1._handle_request({
            "method": "g2.target.set",
            "params": {"target": "10.129.22.74", "scope": "HTB authorized machine"},
        }, "target-set")
        await conn1._handle_request({"method": "g2.action.run", "params": {"id": "hex_recon"}}, "recon")
        approval = ws1.sent[-1]["payload"]["approval"]
        await conn1._handle_request({
            "method": "g2.approval.respond",
            "params": {"id": approval["id"], "optionId": "session-low", "sessionKey": "g2-test"},
        }, "approval-session")
        for job in store.jobs_for_session(ws1.sent[0]["payload"]["session"]["id"], active_only=True):
            await manager.wait_for_job(job["id"])

        ws2, conn2, _manager2 = self.stateful_conn(store, runner)
        await conn2._handle_request({
            "method": "g2.session.resume",
            "params": {"clientSessionId": "client-1", "profileId": "default"},
        }, "resume-2")
        await conn2._handle_request({
            "method": "g2.action.run",
            "params": {"id": "hex_recon", "sessionKey": "g2-test"},
        }, "recon-2")

        response = ws2.sent[-1]
        self.assertEqual(response["payload"]["state"], "running")
        self.assertNotIn("approval", response["payload"])


if __name__ == "__main__":
    unittest.main()
