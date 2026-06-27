from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
from typing import AsyncIterator, Iterable, Optional

from .g2_approval import TargetContext


DEFAULT_ALLOWED_CIDRS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)
DEFAULT_PROJECT_DIR = "/home/titagram/hexstrike-kali-hermes"
DEFAULT_REPORT_BASE_URL = "https://titagram.tail005130.ts.net:8899"
DEFAULT_EXTRA_NMAP = "--host-timeout 60s --max-retries 2"


class HexStrikeTargetError(ValueError):
    """Raised when a G2-requested target is not safe for the direct worker."""


@dataclass(frozen=True)
class HexStrikeRunPlan:
    target: str
    name: str
    command: list[str]
    report_url: str


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    target = re.sub(
        r"^([0-9]+(?:\.[0-9]+){3})\s*[\\/]\s*([0-9]{1,2})$",
        r"\1/\2",
        target,
    )
    target = re.sub(
        r"^([0-9]+(?:\.[0-9]+){3})\s+(/?[0-9]{1,2})$",
        lambda match: f"{match.group(1)}/{match.group(2).lstrip('/')}",
        target,
    )
    return target


def build_scan_name(target: str) -> str:
    normalized = normalize_target(target).lower()
    safe = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return f"g2-{safe[:72] or 'target'}"


def validate_allowed_target(
    raw_target: str,
    allowed_cidrs: Optional[Iterable[str]] = None,
) -> str:
    target = normalize_target(raw_target)
    try:
        network = ipaddress.ip_network(target, strict=False)
    except ValueError as exc:
        raise HexStrikeTargetError("HexStrike target must be an IPv4/IPv6 address or CIDR") from exc

    allowed = _parse_allowed_cidrs(allowed_cidrs)
    if any(network.subnet_of(parent) for parent in allowed):
        return target

    allowed_text = ", ".join(str(network) for network in allowed)
    raise HexStrikeTargetError(f"HexStrike target is outside allowed G2 ranges: {allowed_text}")


class HexStrikeRunner:
    def __init__(
        self,
        project_dir: Optional[str] = None,
        script_path: Optional[str] = None,
        report_base_url: Optional[str] = None,
        allowed_cidrs: Optional[Iterable[str]] = None,
        profile: Optional[str] = None,
        extra_nmap: Optional[str] = None,
    ):
        self.project_dir = Path(project_dir or os.getenv("G2_HEXSTRIKE_PROJECT_DIR", DEFAULT_PROJECT_DIR))
        self.script_path = Path(
            script_path
            or os.getenv("G2_HEXSTRIKE_SCRIPT")
            or self.project_dir / "run-lan-scan.sh"
        )
        self.report_base_url = (
            report_base_url
            or os.getenv("G2_HEXSTRIKE_REPORT_BASE_URL", DEFAULT_REPORT_BASE_URL)
        ).rstrip("/")
        self.allowed_cidrs = _env_list("G2_HEXSTRIKE_ALLOWED_CIDRS") or allowed_cidrs
        self.profile = profile or os.getenv("G2_HEXSTRIKE_PROFILE", "quick")
        self.extra_nmap = extra_nmap if extra_nmap is not None else os.getenv(
            "G2_HEXSTRIKE_EXTRA_NMAP",
            DEFAULT_EXTRA_NMAP,
        )

    def validate_target(self, target: str) -> str:
        return validate_allowed_target(target, self.allowed_cidrs)

    def build_plan(self, target: str) -> HexStrikeRunPlan:
        normalized = self.validate_target(target)
        name = build_scan_name(normalized)
        command = [
            str(self.script_path),
            "--targets",
            normalized,
            "--name",
            name,
            "--profile",
            self.profile,
        ]
        if self.extra_nmap:
            command.extend(["--extra-nmap", self.extra_nmap])
        return HexStrikeRunPlan(
            target=normalized,
            name=name,
            command=command,
            report_url=f"{self.report_base_url}/{name}/",
        )

    async def stream_recon(self, target: TargetContext) -> AsyncIterator[str]:
        plan = self.build_plan(target.target)
        yield f"Starting HexStrike {self.profile} recon for {plan.target}"
        yield f"Report: {plan.report_url}"

        proc = await asyncio.create_subprocess_exec(
            *plan.command,
            cwd=str(self.project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                yield line[:500]

        return_code = await proc.wait()
        if return_code != 0:
            raise RuntimeError(f"HexStrike recon failed with exit code {return_code}")
        yield f"HexStrike recon complete. Report: {plan.report_url}"


def _parse_allowed_cidrs(allowed_cidrs: Optional[Iterable[str]]) -> list[ipaddress._BaseNetwork]:
    values = list(allowed_cidrs) if allowed_cidrs is not None else list(DEFAULT_ALLOWED_CIDRS)
    networks: list[ipaddress._BaseNetwork] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        networks.append(ipaddress.ip_network(text, strict=False))
    return networks


def _env_list(name: str) -> Optional[list[str]]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return None
    return [value.strip() for value in raw_value.split(",") if value.strip()]
