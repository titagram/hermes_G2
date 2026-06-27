import unittest

from src.g2_state import G2StateStore


class G2StateStoreTests(unittest.TestCase):
    def store(self) -> G2StateStore:
        store = G2StateStore(":memory:")
        self.addCleanup(store.close)
        return store

    def test_resume_session_creates_and_reuses_stable_session(self):
        store = self.store()

        created = store.resume_session(
            client_session_id="g2-session-1",
            profile_id="default",
            target="10.129.22.74",
            scope="HTB authorized machine",
            last_seen_event_id=0,
        )
        resumed = store.resume_session(
            client_session_id="g2-session-1",
            profile_id="default",
            last_seen_event_id=0,
        )

        self.assertEqual(created["session"]["id"], resumed["session"]["id"])
        self.assertEqual(resumed["target"]["target"], "10.129.22.74")
        self.assertEqual(resumed["target"]["scope"], "HTB authorized machine")

    def test_events_are_replayed_after_last_seen_id(self):
        store = self.store()
        session = store.resume_session("g2-session-1", "default")["session"]
        first = store.append_event(session["id"], "job.delta", {"line": "started"})
        second = store.append_event(session["id"], "job.delta", {"line": "finished"})

        replay = store.events_since(session["id"], first["eventId"])

        self.assertEqual([event["eventId"] for event in replay], [second["eventId"]])
        self.assertEqual(replay[0]["payload"], {"line": "finished"})

    def test_pending_approvals_and_grants_survive_resume(self):
        store = self.store()
        session = store.resume_session("g2-session-1", "default")["session"]
        approval = {"id": "appr_123", "target": "10.129.22.74", "workflow": "hexstrike-recon"}

        store.save_approval(session["id"], approval, prompt="run recon", ttl_seconds=600)
        store.save_grant(
            session["id"],
            target="10.129.22.74",
            workflow="hexstrike-recon",
            risk_ceiling="low",
            ttl_seconds=1800,
            source_channel="mobile",
        )
        resumed = store.resume_session("g2-session-1", "default")

        self.assertEqual(resumed["pendingApprovals"], [{
            "approval": approval,
            "prompt": "run recon",
        }])
        self.assertEqual(resumed["activeGrants"][0]["target"], "10.129.22.74")
        self.assertEqual(resumed["activeGrants"][0]["riskCeiling"], "low")
        self.assertEqual(resumed["activeGrants"][0]["sourceChannel"], "mobile")

    def test_resolved_approval_is_not_restored(self):
        store = self.store()
        session = store.resume_session("g2-session-1", "default")["session"]
        store.save_approval(session["id"], {"id": "appr_123"}, prompt="run recon", ttl_seconds=600)

        store.resolve_approval(session["id"], "appr_123", "approved")

        resumed = store.resume_session("g2-session-1", "default")
        self.assertEqual(resumed["pendingApprovals"], [])

    def test_job_state_transitions_and_log_are_persisted(self):
        store = self.store()
        session = store.resume_session("g2-session-1", "default")["session"]

        job = store.create_job(
            session["id"],
            workflow="hexstrike-recon",
            target="10.129.22.74",
            state="running",
            command=["/bin/echo", "ok"],
            report_url="https://example.test/report/",
        )
        store.update_job(job["id"], append_log="started")
        updated = store.update_job(job["id"], state="succeeded", exit_code=0, append_log="done")
        jobs = store.jobs_for_session(session["id"])

        self.assertEqual(updated["state"], "succeeded")
        self.assertEqual(updated["exitCode"], 0)
        self.assertEqual(jobs[0]["logTail"], "started\ndone")
        self.assertEqual(jobs[0]["command"], ["/bin/echo", "ok"])

    def test_active_job_lookup_excludes_completed_jobs(self):
        store = self.store()
        session = store.resume_session("g2-session-1", "default")["session"]
        running = store.create_job(session["id"], "hexstrike-recon", "10.129.22.74", "running")
        done = store.create_job(session["id"], "hexstrike-recon", "10.129.22.75", "running")
        store.update_job(done["id"], state="failed", exit_code=1)

        active = store.jobs_for_session(session["id"], active_only=True)

        self.assertEqual([job["id"] for job in active], [running["id"]])


if __name__ == "__main__":
    unittest.main()
