import unittest
import os

from src.g2_approval import ApprovalManager, TargetContext
from src.g2_surface import build_default_surface, find_surface_item, prompt_for_action, server_status_item


class G2SurfaceTests(unittest.TestCase):
    def setUp(self):
        old_health_url = os.environ.get("HEXSTRIKE_HEALTH_URL")
        os.environ["HEXSTRIKE_HEALTH_URL"] = "http://127.0.0.1:1/health"

        def restore_health_url():
            if old_health_url is None:
                os.environ.pop("HEXSTRIKE_HEALTH_URL", None)
            else:
                os.environ["HEXSTRIKE_HEALTH_URL"] = old_health_url

        self.addCleanup(restore_health_url)

    def test_default_surface_has_voice_and_actions(self):
        surface = build_default_surface()

        labels = [item["label"] for item in surface["items"]]

        self.assertIn("VOICE", labels)
        self.assertIn("MAIL", labels)
        self.assertIn("DAILY", labels)
        self.assertEqual(surface["version"], 1)
        self.assertIn(surface["status"]["agent"], {"idle", "busy"})

    def test_action_metadata_stays_server_side(self):
        surface = build_default_surface()

        mail = find_surface_item(surface, "mail")

        self.assertIsNotNone(mail)
        self.assertEqual(mail["type"], "action")
        self.assertEqual(mail["action"]["confirm"], False)
        self.assertEqual(mail["action"]["risk"], "read_only")
        self.assertNotIn("prompt", mail)
        self.assertIn("important unread email", prompt_for_action("mail") or "")

    def test_server_status_item_is_renderable_without_optional_system_files(self):
        item = server_status_item()

        self.assertEqual(item["id"], "server")
        self.assertEqual(item["type"], "data")
        self.assertEqual(item["label"], "SERVER")
        self.assertIsInstance(item["summary"], str)
        self.assertIsInstance(item["detail"], str)
        self.assertGreater(len(item["summary"]), 0)

    def test_hexstrike_surface_items_include_current_target_and_recon(self):
        surface = build_default_surface(target=TargetContext(
            target="10.129.22.74",
            scope="HTB authorized machine",
        ))

        hex_item = find_surface_item(surface, "hex")
        htb_item = find_surface_item(surface, "htb")
        recon_item = find_surface_item(surface, "hex_recon")

        self.assertIsNotNone(hex_item)
        self.assertEqual(hex_item["type"], "data")
        self.assertIsNotNone(htb_item)
        self.assertIn("10.129.22.74", htb_item["summary"])
        self.assertIsNotNone(recon_item)
        self.assertEqual(recon_item["type"], "action")
        self.assertEqual(recon_item["action"]["kind"], "approval")
        self.assertEqual(recon_item["action"]["risk"], "confirm")

    def test_default_surface_includes_model_picker_when_model_is_known(self):
        surface = build_default_surface(model="gemma4:local")
        model = find_surface_item(surface, "model")

        self.assertIsNotNone(model)
        self.assertEqual(model["label"], "MODEL")
        self.assertEqual(model["summary"], "gemma4:local")
        self.assertEqual(model["action"]["kind"], "model_picker")

    def test_pending_approval_is_highest_priority_surface_item(self):
        approvals = ApprovalManager()
        approval = approvals.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        surface = build_default_surface(
            target=TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            pending_approvals=[approval],
        )

        first = surface["items"][0]
        self.assertEqual(first["id"], f"approval:{approval['id']}")
        self.assertEqual(first["label"], "APPROVE")
        self.assertEqual(first["action"]["kind"], "approval")

    def test_active_job_surface_item_is_prominent_and_renderable(self):
        surface = build_default_surface(active_jobs=[{
            "id": "job_123",
            "workflow": "hexstrike-recon",
            "target": "10.129.22.74",
            "state": "running",
            "reportUrl": "https://reports.example/10.129.22.74/",
            "logTail": "started\nnmap running",
        }])

        job = find_surface_item(surface, "job:job_123")

        self.assertIsNotNone(job)
        self.assertEqual(job["type"], "data")
        self.assertEqual(job["label"], "JOB")
        self.assertIn("running", job["summary"])
        self.assertIn("nmap running", job["detail"])
        self.assertGreater(job["priority"], 100)

    def test_completed_job_surface_item_keeps_report_visible_below_approvals(self):
        approvals = ApprovalManager()
        approval = approvals.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        surface = build_default_surface(
            pending_approvals=[approval],
            active_jobs=[{
                "id": "job_done",
                "workflow": "hexstrike-recon",
                "target": "10.129.22.74",
                "state": "succeeded",
                "reportUrl": "https://reports.example/10.129.22.74/",
                "logTail": "HexStrike recon complete.",
            }],
        )

        self.assertEqual(surface["items"][0]["label"], "APPROVE")
        job = find_surface_item(surface, "job:job_done")
        self.assertIsNotNone(job)
        self.assertIn("succeeded", job["summary"])
        self.assertIn("https://reports.example/10.129.22.74/", job["detail"])


if __name__ == "__main__":
    unittest.main()
