import unittest

from src.g2_hexstrike import (
    HexStrikeTargetError,
    build_scan_name,
    normalize_target,
    validate_allowed_target,
)


class G2HexStrikeTests(unittest.TestCase):
    def test_normalizes_spoken_or_split_cidr(self):
        self.assertEqual(normalize_target("192.168.1.0 /24"), "192.168.1.0/24")
        self.assertEqual(normalize_target("192.168.1.0 \\24"), "192.168.1.0/24")

    def test_allows_private_single_host_and_cidr_targets(self):
        self.assertEqual(validate_allowed_target("192.168.1.1"), "192.168.1.1")
        self.assertEqual(validate_allowed_target("192.168.1.0/24"), "192.168.1.0/24")

    def test_rejects_public_cidr_by_default(self):
        with self.assertRaises(HexStrikeTargetError):
            validate_allowed_target("192.169.1.0/24")

    def test_builds_stable_scan_name(self):
        self.assertEqual(build_scan_name("192.168.1.0/24"), "g2-192-168-1-0-24")


if __name__ == "__main__":
    unittest.main()
