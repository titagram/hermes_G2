import unittest

from src.bridge_server import HermesClient, HermesSttError


class _FakeSttClient(HermesClient):
    def __init__(self, provider: str):
        super().__init__(
            "http://unused",
            "",
            stt_provider=provider,
            local_stt_model="tiny",
        )
        self.hermes_calls = 0
        self.local_calls = 0

    async def _transcribe_audio_hermes(self, audio_bytes, filename, mime_type, model):
        self.hermes_calls += 1
        raise HermesSttError(404, "Not Found")

    async def _transcribe_audio_local(self, audio_bytes):
        self.local_calls += 1
        return "ciao hermes"


class HermesClientSttTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_provider_bypasses_hermes_stt_endpoint(self):
        client = _FakeSttClient("local")

        text = await client.transcribe_audio(b"RIFF")

        self.assertEqual(text, "ciao hermes")
        self.assertEqual(client.hermes_calls, 0)
        self.assertEqual(client.local_calls, 1)

    async def test_auto_provider_falls_back_to_local_after_hermes_404(self):
        client = _FakeSttClient("auto")

        with self.assertLogs("hermes-glass", level="WARNING") as logs:
            first = await client.transcribe_audio(b"RIFF")
        second = await client.transcribe_audio(b"RIFF")

        self.assertEqual(first, "ciao hermes")
        self.assertEqual(second, "ciao hermes")
        self.assertEqual(client.hermes_calls, 1)
        self.assertEqual(client.local_calls, 2)
        self.assertTrue(any("using local STT fallback" in line for line in logs.output))
