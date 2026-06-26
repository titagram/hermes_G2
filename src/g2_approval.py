from __future__ import annotations

from dataclasses import dataclass
import time
import uuid
from typing import Any, Dict, List, Optional


RISK_ORDER = {
    "read_only": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "dangerous": 4,
}


@dataclass(frozen=True)
class TargetContext:
    target: str = ""
    scope: str = ""


@dataclass
class _ApprovalRecord:
    approval: Dict[str, Any]
    prompt: str
    created_at: float


@dataclass
class _SessionGrant:
    target: str
    workflow: str
    risk_ceiling: str
    expires_at: float


class ApprovalManager:
    """Small per-connection approval queue and bounded session grant store."""

    def __init__(self):
        self._pending: Dict[str, _ApprovalRecord] = {}
        self._grants: List[_SessionGrant] = []

    def create_recon_approval(self, target: TargetContext, prompt: str) -> Dict[str, Any]:
        approval_id = f"appr_{uuid.uuid4().hex[:12]}"
        target_value = target.target.strip()
        approval = {
            "id": approval_id,
            "title": "Quick recon",
            "target": target_value,
            "workflow": "hexstrike-recon",
            "risk": "low",
            "reason": "Run non-destructive service reconnaissance.",
            "detail": (
                "Quick recon\n"
                f"Target: {target_value or 'not set'}\n"
                f"Scope: {target.scope.strip() or 'not set'}\n"
                "Risk: low\n"
                "Hermes will use the hexstrike-kali-htb skill and only perform "
                "read-only reconnaissance unless another approval is requested."
            ),
            "options": [
                {"id": "once", "label": "ONCE", "kind": "approve_once"},
                {
                    "id": "session-low",
                    "label": "SESSION LOW",
                    "kind": "approve_session",
                    "riskCeiling": "low",
                    "ttlMinutes": 30,
                },
                {
                    "id": "session-medium",
                    "label": "SESSION MED",
                    "kind": "approve_session",
                    "riskCeiling": "medium",
                    "ttlMinutes": 15,
                },
                {"id": "deny", "label": "DENY", "kind": "deny"},
                {"id": "detail", "label": "DETAIL", "kind": "detail"},
            ],
        }
        self._pending[approval_id] = _ApprovalRecord(approval=approval, prompt=prompt, created_at=time.time())
        return dict(approval)

    def pending(self) -> List[Dict[str, Any]]:
        return [dict(record.approval) for record in self._pending.values()]

    def get(self, approval_id: str) -> Optional[Dict[str, Any]]:
        record = self._pending.get(approval_id)
        return dict(record.approval) if record else None

    def respond(self, approval_id: str, option_id: str) -> Dict[str, Any]:
        record = self._pending.get(approval_id)
        if record is None:
            return {"state": "missing", "error": "approval not found"}

        option = self._find_option(record.approval, option_id)
        if option is None:
            return {"state": "missing", "error": "approval option not found"}

        kind = option.get("kind")
        if kind == "detail":
            return {
                "state": "detail",
                "item": {
                    "id": f"approval-detail:{approval_id}",
                    "type": "data",
                    "label": "APPROVAL",
                    "summary": str(record.approval.get("title") or "detail"),
                    "detail": str(record.approval.get("detail") or ""),
                    "priority": 100,
                },
            }

        self._pending.pop(approval_id, None)
        if kind == "deny":
            return {"state": "denied", "accepted": False, "id": approval_id}

        if kind == "approve_session":
            ttl_minutes = int(option.get("ttlMinutes") or 0)
            risk_ceiling = str(option.get("riskCeiling") or record.approval.get("risk") or "low")
            self._grants.append(_SessionGrant(
                target=str(record.approval.get("target") or ""),
                workflow=str(record.approval.get("workflow") or ""),
                risk_ceiling=risk_ceiling,
                expires_at=time.time() + max(1, ttl_minutes) * 60,
            ))

        return {
            "state": "running",
            "accepted": True,
            "id": approval_id,
            "prompt": record.prompt,
            "grant": option,
        }

    def is_granted(self, target: str, workflow: str, risk: str) -> bool:
        now = time.time()
        self._grants = [grant for grant in self._grants if grant.expires_at > now]
        requested = RISK_ORDER.get(risk, RISK_ORDER["dangerous"])
        for grant in self._grants:
            if grant.target != target or grant.workflow != workflow:
                continue
            if requested <= RISK_ORDER.get(grant.risk_ceiling, -1):
                return True
        return False

    @staticmethod
    def _find_option(approval: Dict[str, Any], option_id: str) -> Optional[Dict[str, Any]]:
        for option in approval.get("options", []):
            if isinstance(option, dict) and option.get("id") == option_id:
                return option
        return None
