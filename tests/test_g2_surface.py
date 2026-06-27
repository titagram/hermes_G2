import unittest

from src.g2_surface import build_default_surface, find_surface_item, prompt_for_action, server_status_item


class G2SurfaceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
