from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional


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


def build_default_surface(agent_state: str = "idle") -> Surface:
    now = int(time.time() * 1000)
    return {
        "version": 1,
        "updatedAt": now,
        "status": {"agent": agent_state, "connection": "ok"},
        "items": [
            server_status_item(),
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
        ],
    }


def find_surface_item(surface: Surface, item_id: str) -> Optional[dict[str, Any]]:
    for item in surface.get("items", []):
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def prompt_for_action(action_id: str) -> Optional[str]:
    return DEFAULT_ACTION_PROMPTS.get(action_id)
