import unittest

from src.g2_approval import ApprovalManager, TargetContext


class G2ApprovalTests(unittest.TestCase):
    def test_recon_approval_options_are_configurable_per_request(self):
        manager = ApprovalManager()
        approval = manager.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        self.assertEqual(approval["title"], "Quick recon")
        self.assertEqual(approval["target"], "10.129.22.74")
        self.assertEqual([option["id"] for option in approval["options"]], [
            "once",
            "session-low",
            "session-medium",
            "deny",
            "detail",
        ])
        self.assertEqual(approval["options"][1]["riskCeiling"], "low")
        self.assertEqual(approval["options"][2]["riskCeiling"], "medium")

    def test_detail_response_keeps_approval_pending(self):
        manager = ApprovalManager()
        approval = manager.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        result = manager.respond(approval["id"], "detail")

        self.assertEqual(result["state"], "detail")
        self.assertIn("Quick recon", result["item"]["detail"])
        self.assertEqual(len(manager.pending()), 1)

    def test_deny_removes_pending_approval(self):
        manager = ApprovalManager()
        approval = manager.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        result = manager.respond(approval["id"], "deny")

        self.assertEqual(result["state"], "denied")
        self.assertEqual(manager.pending(), [])

    def test_approve_once_returns_prompt_without_session_grant(self):
        manager = ApprovalManager()
        approval = manager.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        result = manager.respond(approval["id"], "once")

        self.assertEqual(result["state"], "running")
        self.assertEqual(result["prompt"], "run recon")
        self.assertFalse(manager.is_granted("10.129.22.74", "hexstrike-recon", "low"))
        self.assertEqual(manager.pending(), [])

    def test_session_approval_is_limited_by_target_workflow_and_risk(self):
        manager = ApprovalManager()
        approval = manager.create_recon_approval(
            TargetContext(target="10.129.22.74", scope="HTB authorized machine"),
            prompt="run recon",
        )

        result = manager.respond(approval["id"], "session-low")

        self.assertEqual(result["state"], "running")
        self.assertTrue(manager.is_granted("10.129.22.74", "hexstrike-recon", "low"))
        self.assertFalse(manager.is_granted("10.129.22.74", "hexstrike-recon", "medium"))
        self.assertFalse(manager.is_granted("10.129.22.75", "hexstrike-recon", "low"))
        self.assertFalse(manager.is_granted("10.129.22.74", "other-workflow", "low"))

    def test_restore_pending_approval_can_be_approved_after_reconnect(self):
        manager = ApprovalManager()
        approval = {
            "id": "appr_restore",
            "title": "Quick recon",
            "target": "10.129.22.74",
            "scope": "HTB authorized machine",
            "workflow": "hexstrike-recon",
            "risk": "low",
            "detail": "Quick recon\nTarget: 10.129.22.74",
            "options": [
                {"id": "once", "label": "ONCE", "kind": "approve_once"},
                {"id": "deny", "label": "DENY", "kind": "deny"},
            ],
        }

        manager.restore_pending(approval, prompt="run restored recon")
        result = manager.respond("appr_restore", "once")

        self.assertEqual(result["state"], "running")
        self.assertEqual(result["prompt"], "run restored recon")
        self.assertEqual(manager.pending(), [])

    def test_restore_unexpired_grant_allows_matching_low_risk_workflow(self):
        manager = ApprovalManager()

        manager.restore_grant(
            target="10.129.22.74",
            workflow="hexstrike-recon",
            risk_ceiling="low",
            expires_at_ms=4_102_444_800_000,
        )

        self.assertTrue(manager.is_granted("10.129.22.74", "hexstrike-recon", "low"))
        self.assertFalse(manager.is_granted("10.129.22.74", "hexstrike-recon", "medium"))


if __name__ == "__main__":
    unittest.main()
