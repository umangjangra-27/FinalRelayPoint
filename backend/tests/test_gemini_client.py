"""Unit tests for lightweight Gemini API client integration."""

from io import BytesIO
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from app.integrations.gemini import (
    GeminiAuthError,
    GeminiClient,
    GeminiError,
    GeminiModelNotFoundError,
    GeminiQuotaError,
    GeminiResponseError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)


class TestGeminiClient(unittest.TestCase):
    """Test suite for Gemini REST client."""

    def test_missing_api_key_raises_auth_error(self):
        """Verify calling client without an API key immediately raises GeminiAuthError."""
        client = GeminiClient(api_key="")
        with self.assertRaises(GeminiAuthError):
            client.generate_structured_json(prompt="Test prompt")

    @patch("urllib.request.urlopen")
    def test_successful_structured_json_response(self, mock_urlopen):
        """Verify valid candidate payload extraction and JSON parsing."""
        mock_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "project_summary": "Test project summary",
                                    "architectural_decisions": [],
                                })
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = GeminiClient(api_key="synthetic_fake_key", model="gemini-2.5-flash")
        result = client.generate_structured_json(prompt="Analyze repo")

        self.assertIn("project_summary", result)
        self.assertEqual(result["project_summary"], "Test project summary")

        # Verify API key is passed in header and NOT in URL query string
        sent_req = mock_urlopen.call_args[0][0]
        self.assertNotIn("key=", sent_req.full_url)
        self.assertNotIn("synthetic_fake_key", sent_req.full_url)
        self.assertEqual(sent_req.get_header("X-goog-api-key"), "synthetic_fake_key")

    @patch("urllib.request.urlopen")
    def test_handles_markdown_wrapped_json(self, mock_urlopen):
        """Verify markdown code block wrappers (```json ... ```) are cleanly stripped."""
        wrapped_json = "```json\n{\"project_summary\": \"Markdown wrapped\"}\n```"
        mock_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": wrapped_json}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = GeminiClient(api_key="synthetic_key")
        result = client.generate_structured_json("Prompt")
        self.assertEqual(result["project_summary"], "Markdown wrapped")

    @patch("urllib.request.urlopen")
    def test_quota_error_429(self, mock_urlopen):
        """Verify HTTP 429 raises GeminiQuotaError."""
        http_err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=429,
            msg="Resource Exhausted",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Resource has been exhausted"}}'),
        )
        mock_urlopen.side_effect = http_err

        client = GeminiClient(api_key="synthetic_key")
        with self.assertRaises(GeminiQuotaError):
            client.generate_structured_json("Prompt")

    @patch("urllib.request.urlopen")
    def test_model_not_found_404(self, mock_urlopen):
        """Verify HTTP 404 raises GeminiModelNotFoundError."""
        http_err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Model not found"}}'),
        )
        mock_urlopen.side_effect = http_err

        client = GeminiClient(api_key="synthetic_key", model="invalid-model-name")
        with self.assertRaises(GeminiModelNotFoundError):
            client.generate_structured_json("Prompt")

    @patch("urllib.request.urlopen")
    def test_malformed_json_raises_response_error(self, mock_urlopen):
        """Verify non-JSON response raises GeminiResponseError."""
        mock_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "I am not a JSON object."}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = GeminiClient(api_key="synthetic_key")
        with self.assertRaises(GeminiResponseError):
            client.generate_structured_json("Prompt")

    @patch("urllib.request.urlopen")
    def test_request_body_structured_output_schema_placement(self, mock_urlopen):
        """Verify request body structure, responseMimeType, and responseSchema placement in generationConfig."""
        mock_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": json.dumps({"project_summary": "Schema verified"})}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = GeminiClient(api_key="synthetic_test_key", model="gemini-3.8-flash")
        sample_schema = {
            "type": "object",
            "properties": {"project_summary": {"type": "string"}},
            "required": ["project_summary"],
        }

        result = client.generate_structured_json(
            prompt="Analyze repository context",
            system_instruction="Strict JSON output only",
            temperature=0.1,
            response_schema=sample_schema,
        )

        self.assertEqual(result["project_summary"], "Schema verified")

        # Inspect exact outbound request payload sent via urllib
        sent_req = mock_urlopen.call_args[0][0]
        sent_body = json.loads(sent_req.data.decode("utf-8"))

        # Verify generationConfig placement
        self.assertIn("generationConfig", sent_body)
        gen_cfg = sent_body["generationConfig"]
        self.assertEqual(gen_cfg.get("responseMimeType"), "application/json")
        self.assertEqual(gen_cfg.get("temperature"), 0.1)
        self.assertEqual(gen_cfg.get("responseSchema"), sample_schema)

        # Verify contents and system instruction
        self.assertEqual(sent_body["contents"][0]["parts"][0]["text"], "Analyze repository context")
        self.assertEqual(sent_body["systemInstruction"]["parts"][0]["text"], "Strict JSON output only")
        self.assertEqual(sent_req.get_header("X-goog-api-key"), "synthetic_test_key")

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_transient_503_retry_and_succeed(self, mock_urlopen, mock_sleep):
        """Verify transient 503 error triggers retry with backoff and succeeds on subsequent attempt."""
        err_503 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Backend temporarily overloaded"}}'),
        )
        mock_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": json.dumps({"project_summary": "Recovered from 503"})}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        mock_urlopen.side_effect = [err_503, mock_resp]

        client = GeminiClient(api_key="synthetic_key", max_retries=2, initial_backoff=0.01)
        result = client.generate_structured_json("Prompt")

        self.assertEqual(result["project_summary"], "Recovered from 503")
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_transient_503_retry_exhaustion_raises_unavailable(self, mock_urlopen, mock_sleep):
        """Verify exhausting retries on 503 raises GeminiUnavailableError."""
        err_503 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Service down"}}'),
        )
        mock_urlopen.side_effect = err_503

        client = GeminiClient(api_key="synthetic_key", max_retries=2, initial_backoff=0.01)
        with self.assertRaises(GeminiUnavailableError) as ctx:
            client.generate_structured_json("Prompt")

        self.assertIn("temporarily unavailable", str(ctx.exception).lower())
        # Initial attempt + 2 retries = 3 calls
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_permanent_400_fails_immediately_without_retry(self, mock_urlopen):
        """Verify permanent client error (400) fails immediately on first attempt without retrying."""
        err_400 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "Invalid argument format"}}'),
        )
        mock_urlopen.side_effect = err_400

        client = GeminiClient(api_key="synthetic_key", max_retries=3)
        with self.assertRaises(GeminiError) as ctx:
            client.generate_structured_json("Prompt")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_permanent_401_fails_immediately_without_retry(self, mock_urlopen):
        """Verify authentication error (401) fails immediately on first attempt without retrying."""
        err_401 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=BytesIO(b'{"error": {"message": "API key invalid"}}'),
        )
        mock_urlopen.side_effect = err_401

        client = GeminiClient(api_key="synthetic_key", max_retries=3)
        with self.assertRaises(GeminiAuthError):
            client.generate_structured_json("Prompt")

        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_socket_timeout_retries_and_raises_timeout_error(self, mock_urlopen, mock_sleep):
        """Verify network/socket timeout retries and eventually raises GeminiTimeoutError."""
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")

        client = GeminiClient(api_key="synthetic_key", max_retries=1, initial_backoff=0.01)
        with self.assertRaises(GeminiTimeoutError) as ctx:
            client.generate_structured_json("Prompt")

        self.assertIn("timed out", str(ctx.exception).lower())
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_configurable_model_in_request_url(self, mock_urlopen):
        """Verify GEMINI_MODEL setting dynamically dictates the API URL."""
        mock_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": json.dumps({"project_summary": "Model custom"})}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = GeminiClient(api_key="synthetic_key", model="gemini-2.0-flash-exp")
        client.generate_structured_json("Prompt")

        sent_req = mock_urlopen.call_args[0][0]
        self.assertIn("/gemini-2.0-flash-exp:generateContent", sent_req.full_url)


if __name__ == "__main__":
    unittest.main()
