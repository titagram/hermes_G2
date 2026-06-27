import asyncio
import unittest

from src.g2_approval import TargetContext
from src.g2_hexstrike import HexStrikeRunPlan
from src.g2_jobs import G2JobManager
from src.g2_state import G2StateStore


class FakeRunner:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def build_plan(self, target):
        return HexStrikeRunPlan(
            target=target,
            name=f"g2-{target.replace('.', '-')}",
            command=["scan", target],
            report_url=f"https://reports.example/{target}/",
        )

    async def stream_recon(self, target):
        self.calls += 1
        yield f"started {target.target}"
        if self.fail:
            raise RuntimeError("boom")
        yield "done"


class SlowRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()

    async def stream_recon(self, target):
        self.calls += 1
        yield f"started {target.target}"
        await self.release.wait()
        yield "done"


class G2JobManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = G2StateStore(":memory:")
        self.addCleanup(self.store.close)
        self.session = self.store.resume_session("g2-session-1", "default")["session"]

    async def test_recon_job_emits_events_and_persists_success(self):
        runner = FakeRunner()
        manager = G2JobManager(self.store, runner=runner)
        received = []
        manager.subscribe(self.session["id"], lambda event, payload: received.append((event, payload)))

        job = await manager.start_recon(
            self.session["id"],
            TargetContext(target="10.129.22.74", scope="HTB"),
            session_key="g2-test",
        )
        finished = await manager.wait_for_job(job["id"])

        self.assertEqual(finished["state"], "succeeded")
        self.assertEqual(runner.calls, 1)
        self.assertIn("started 10.129.22.74", finished["logTail"])
        self.assertEqual(finished["command"], ["scan", "10.129.22.74"])
        self.assertTrue(any(event == "chat.event" and payload["state"] == "final" for event, payload in received))
        self.assertTrue(all("eventId" in payload for _, payload in received))

    async def test_recon_job_marks_failure_and_emits_completion_error(self):
        manager = G2JobManager(self.store, runner=FakeRunner(fail=True))
        received = []
        manager.subscribe(self.session["id"], lambda event, payload: received.append((event, payload)))

        job = await manager.start_recon(
            self.session["id"],
            TargetContext(target="10.129.22.74", scope="HTB"),
            session_key="g2-test",
        )
        finished = await manager.wait_for_job(job["id"])

        self.assertEqual(finished["state"], "failed")
        self.assertEqual(finished["exitCode"], 1)
        self.assertIn("HexStrike recon failed: boom", finished["logTail"])
        completion = [payload for event, payload in received if event == "agent.completion"][-1]
        self.assertEqual(completion["status"], "error")

    async def test_duplicate_active_recon_returns_existing_job(self):
        runner = SlowRunner()
        manager = G2JobManager(self.store, runner=runner)

        first = await manager.start_recon(
            self.session["id"],
            TargetContext(target="10.129.22.74", scope="HTB"),
            session_key="g2-test",
        )
        await asyncio.sleep(0)
        second = await manager.start_recon(
            self.session["id"],
            TargetContext(target="10.129.22.74", scope="HTB"),
            session_key="g2-test",
        )

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["duplicate"], True)
        runner.release.set()
        await manager.wait_for_job(first["id"])
        self.assertEqual(runner.calls, 1)


if __name__ == "__main__":
    unittest.main()
