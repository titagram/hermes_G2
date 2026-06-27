from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .g2_approval import TargetContext


Surface = Dict[str, Any]


DEFAULT_ACTION_PROMPTS = {
    "mail": "Read my important unread email and summarize what needs action.",
    "daily": "Give me my daily briefing for today.",
}


def _read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                key, raw = line.split(":", 1)
                value = raw.strip().split()[0]
                if value.isdigit():
                    result[key] = int(value)
    except (OSError, ValueError):
        return {}
    return result


def _memory_summary() -> str:
    mem = _read_meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    if total <= 0 or available < 0:
        return "RAM n/a"
    used_pct = round((1 - available / total) * 100)
    return f"RAM {used_pct}%"


def _load_summary() -> str:
    try:
        load1, _, _ = os.getloadavg()
        return f"LOAD {load1:.2f}"
    except OSError:
        return "LOAD n/a"


def server_status_item() -> dict[str, Any]:
    load = _load_summary()
    memory = _memory_summary()
    return {
        "id": "server",
        "type": "data",
        "label": "SERVER",
        "summary": f"{load} {memory}",
        "detail": f"Server status\n{load}\n{memory}",
        "priority": 30,
    }


def hexstrike_health_item() -> dict[str, Any]:
    url = os.getenv("HEXSTRIKE_HEALTH_URL", "http://127.0.0.1:8888/health")
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            payload = response.read(48_000)
        import json
        health = json.loads(payload.decode("utf-8", errors="replace"))
        telemetry = health.get("telemetry", {}) if isinstance(health, dict) else {}
        metrics = telemetry.get("system_metrics", {}) if isinstance(telemetry, dict) else {}
        status = str(health.get("status", "unknown"))
        commands = telemetry.get("commands_executed", 0)
        memory = metrics.get("memory_percent", "?")
        cpu = metrics.get("cpu_percent", "?")
        essentials = "tools ok" if health.get("all_essential_tools_available") else "tools missing"
        summary = f"{status} {commands} cmds"
        detail = (
            "HexStrike\n"
            f"Status: {status}\n"
            f"Essential: {essentials}\n"
            f"Commands: {commands}\n"
            f"CPU: {cpu}%\n"
            f"Memory: {memory}%"
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        summary = "offline"
        detail = "HexStrike\nStatus: unavailable\nServer health endpoint did not respond."

    return {
        "id": "hex",
        "type": "data",
        "label": "HEX",
        "summary": summary,
        "detail": detail,
        "priority": 28,
    }


def htb_status_item(target: TargetContext) -> dict[str, Any]:
    target_value = target.target.strip()
    scope = target.scope.strip()
    summary = target_value if target_value else "target not set"
    detail = (
        "HTB target\n"
        f"Target: {target_value or 'not set'}\n"
        f"Scope: {scope or 'not set'}\n"
        "Report: https://titagram.tail005130.ts.net:8899/engagements/current/"
    )
    return {
        "id": "htb",
        "type": "data",
        "label": "HTB",
        "summary": summary,
        "detail": detail,
        "priority": 26,
    }


def recon_action_item(target: TargetContext) -> dict[str, Any]:
    target_value = target.target.strip()
    return {
        "id": "hex_recon",
        "type": "action",
        "label": "RECON",
        "summary": target_value or "set target",
        "priority": 24,
        "action": {"kind": "approval", "confirm": True, "risk": "confirm"},
    }


def approval_surface_item(approval: dict[str, Any]) -> dict[str, Any]:
    approval_id = str(approval.get("id", "")).strip()
    title = str(approval.get("title", "approval")).strip()
    target = str(approval.get("target", "")).strip()
    return {
        "id": f"approval:{approval_id}",
        "type": "action",
        "label": "APPROVE",
        "summary": f"{title} {target}".strip(),
        "detail": str(approval.get("detail", "")),
        "priority": 1000,
        "action": {"kind": "approval", "confirm": True, "risk": "confirm"},
    }


def job_surface_item(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id", "")).strip()
    state = str(job.get("state", "unknown")).strip() or "unknown"
    workflow = str(job.get("workflow", "job")).strip() or "job"
    target = str(job.get("target", "")).strip()
    report_url = str(job.get("reportUrl", "")).strip()
    log_tail = str(job.get("logTail", "")).strip()
    is_active = state in {"queued", "running"}
    priority = 900 if is_active else 80 if state == "failed" else 60
    summary = f"{workflow.replace('hexstrike-', '').upper()} {state}"
    if target:
        summary = f"{summary} {target}"
    detail_lines = [
        "HexStrike job",
        f"State: {state}",
        f"Target: {target or 'not set'}",
    ]
    if report_url:
        detail_lines.append(f"Report: {report_url}")
    if log_tail:
        detail_lines.extend(["Recent:", log_tail[-900:]])
    return {
        "id": f"job:{job_id}",
        "type": "data",
        "label": "JOB",
        "summary": summary,
        "detail": "\n".join(detail_lines),
        "priority": priority,
    }


def build_default_surface(
    agent_state: str = "idle",
    target: Optional[TargetContext] = None,
    pending_approvals: Optional[List[dict[str, Any]]] = None,
    active_jobs: Optional[List[dict[str, Any]]] = None,
) -> Surface:
    now = int(time.time() * 1000)
    target = target or TargetContext()
    approvals = pending_approvals or []
    jobs = active_jobs or []
    items = [
        *(approval_surface_item(approval) for approval in approvals),
        *(job_surface_item(job) for job in jobs[:3]),
        server_status_item(),
        hexstrike_health_item(),
        htb_status_item(target),
        recon_action_item(target),
        {
            "id": "mail",
            "type": "action",
            "label": "MAIL",
            "summary": "important unread",
            "priority": 20,
            "action": {"kind": "run_prompt", "confirm": False, "risk": "read_only"},
        },
        {
            "id": "daily",
            "type": "action",
            "label": "DAILY",
            "summary": "briefing",
            "priority": 10,
            "action": {"kind": "run_prompt", "confirm": False, "risk": "read_only"},
        },
        {
            "id": "voice",
            "type": "voice",
            "label": "VOICE",
            "summary": "press to talk",
            "priority": 0,
        },
    ]
    return {
        "version": 1,
        "updatedAt": now,
        "status": {"agent": agent_state, "connection": "ok"},
        "items": sorted(items, key=lambda item: -int(item.get("priority", 0))),
    }


def find_surface_item(surface: Surface, item_id: str) -> Optional[dict[str, Any]]:
    for item in surface.get("items", []):
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def prompt_for_action(action_id: str) -> Optional[str]:
    return DEFAULT_ACTION_PROMPTS.get(action_id)
