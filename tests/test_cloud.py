import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import cloud


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class GeminiRetryTests(unittest.TestCase):
    def config(self):
        return {
            "model": "primary-model",
            "fallback_models": ["fallback-model"],
            "api_attempts": 1,
            "max_output_tokens": 32,
            "api_timeout_seconds": 1,
        }

    def response(self):
        return _Response(json.dumps({
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": "{\"ok\": true}"}]}],
        }).encode())

    def test_transient_failure_uses_configured_fallback(self):
        error = HTTPError(
            "https://example.invalid", 503, "overloaded",
            {"Retry-After": "0"}, io.BytesIO(b'{"error":{"message":"busy"}}'),
        )
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data))
            if len(requests) == 1:
                raise error
            return self.response()

        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}), \
             patch.object(cloud, "urlopen", side_effect=fake_urlopen):
            result = cloud.generate(self.config(), "prompt", {"type": "object"}, Path(temp) / "audit.json")

        self.assertEqual(result, {"ok": True})
        self.assertEqual([item["model"] for item in requests], ["primary-model", "fallback-model"])

    def test_non_transient_failure_is_not_hidden_by_fallback(self):
        error = HTTPError(
            "https://example.invalid", 400, "bad request", {},
            io.BytesIO(b'{"error":{"message":"invalid test-key"}}'),
        )
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}), \
             patch.object(cloud, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, r"Gemini HTTP 400: invalid \[redacted\]"):
                cloud.generate(self.config(), "prompt", {"type": "object"}, Path(temp) / "audit.json")


if __name__ == "__main__":
    unittest.main()
