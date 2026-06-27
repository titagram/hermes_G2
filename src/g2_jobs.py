from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from .g2_approval import TargetContext
from .g2_hexstrike import HexStrikeRunner
from .g2_state import G2StateStore


logger = logging.getLogger("hermes-glass")
JobSubscriber = Callable[[str, dict[str, Any]], Optional[Awaitable[None]]]


class G2JobManager:
    """Owns long-running G2 jobs independently from any single WebSocket."""

    def __init__(self, store: G2StateStore, runner: Optional[HexStrikeRunner] = None):
        self.store = store
        self.runner = runner or HexStrikeRunner()
        self._subscribers: dict[str, set[JobSubscriber]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, session_id: str, callback: JobSubscriber) -> Callable[[], None]:
        callbacks = self._subscribers.setdefault(session_id, set())
        callbacks.add(callback)

        def unsubscribe() -> None:
            callbacks.discard(callback)
            if not callbacks:
                self._subscribers.pop(session_id, None)

        return unsubscribe

    async def start_recon(
        self,
        session_id: str,
        target: TargetContext,
        session_key: str = "g2-hermes",
    ) -> dict[str, Any]:
        plan = self.runner.build_plan(target.target)
        async with self._lock:
            active = self.store.active_job(session_id, "hexstrike-recon", plan.target)
            if active is not None:
                active["duplicate"] = True
                return active

            job = self.store.create_job(
                session_id=session_id,
                workflow="hexstrike-recon",
                target=plan.target,
                state="running",
                command=plan.command,
                report_url=plan.report_url,
            )
            task = asyncio.create_task(self._run_recon_job(job["id"], target, session_key))
            self._tasks[job["id"]] = task
            task.add_done_callback(lambda _task, job_id=job["id"]: self._tasks.pop(job_id, None))
            return job

    async def wait_for_job(self, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return self.store.get_job(job_id)

    async def _run_recon_job(self, job_id: str, target: TargetContext, session_key: str) -> None:
        job = self.store.get_job(job_id)
        session_id = job["sessionId"]
        run_id = job_id
        seq = 0
        accumulated = ""
        status = "ok"
        final_text = ""

        await self._emit(session_id, "agent.event", {
            "runId": run_id,
            "seq": seq,
            "stream": "hermes-main",
            "ts": int(time.time() * 1000),
            "data": {"sessionKey": session_key, "status": "busy", "jobId": job_id},
        })
        await self._emit(session_id, "g2.job.event", {
            "jobId": job_id,
            "state": "running",
            "target": job["target"],
            "workflow": job["workflow"],
            "reportUrl": job["reportUrl"],
        })

        try:
            async for line in self.runner.stream_recon(target):
                clean = str(line).strip()
                if not clean:
                    continue
                self.store.update_job(job_id, append_log=clean)
                accumulated = (accumulated + "\n" + clean).strip()[-1800:]
                seq += 1
                await self._emit(session_id, "chat.event", {
                    "runId": run_id,
                    "sessionKey": session_key,
                    "seq": seq,
                    "state": "delta",
                    "message": {"role": "assistant", "content": accumulated},
                    "jobId": job_id,
                })
            final_text = accumulated or "HexStrike recon finished without output."
            self.store.update_job(job_id, state="succeeded")
        except Exception as exc:
            status = "error"
            final_text = f"HexStrike recon failed: {exc}"
            self.store.update_job(job_id, state="failed", exit_code=1, append_log=final_text)
            logger.info("HexStrike recon job %s failed for %s: %s", job_id, target.target, exc)

        seq += 1
        await self._emit(session_id, "chat.event", {
            "runId": run_id,
            "sessionKey": session_key,
            "seq": seq,
            "state": "final",
            "message": {"role": "assistant", "content": final_text},
            "stopReason": "stop" if status == "ok" else "error",
            "jobId": job_id,
        })
        await self._emit(session_id, "agent.event", {
            "runId": run_id,
            "seq": seq + 1,
            "stream": "hermes-main",
            "ts": int(time.time() * 1000),
            "data": {"sessionKey": session_key, "status": "idle", "jobId": job_id},
        })
        await self._emit(session_id, "agent.completion", {
            "agentId": "hermes-main",
            "sessionKey": session_key,
            "runId": run_id,
            "status": status,
            "result": final_text,
            "timestamp": int(time.time() * 1000),
            "jobId": job_id,
        })

    async def _emit(self, session_id: str, event_name: str, payload: dict[str, Any]) -> None:
        record = self.store.append_event(session_id, event_name, payload)
        event_payload = dict(payload)
        event_payload["eventId"] = record["eventId"]
        event_payload["createdAt"] = record["createdAt"]
        callbacks = list(self._subscribers.get(session_id, set()))
        for callback in callbacks:
            try:
                result = callback(event_name, event_payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("G2 job subscriber failed for session %s", session_id)
