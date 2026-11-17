"""Lightweight Google Gemini REST API Client.

Uses Python standard-library urllib.request to interact with the Gemini API,
enforcing JSON structured outputs, connection timeouts, and bounded retries with
exponential backoff.
"""

import json
import logging
import socket
import time
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

from app.core.config import get_settings

logger = logging.getLogger("relaypoint.gemini")

GEMINI_API_HOST = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiError(Exception):
    """Base exception for Gemini operations."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GeminiAuthError(GeminiError):
    """Raised when API key is missing, unauthorized, or invalid (HTTP 401/403)."""
    pass


class GeminiQuotaError(GeminiError):
    """Raised when quota or rate limits are exceeded after retries (HTTP 429)."""
    pass


class GeminiModelNotFoundError(GeminiError):
    """Raised when the specified model does not exist or is unavailable (HTTP 404)."""
    pass


class GeminiResponseError(GeminiError):
    """Raised when the model response is malformed, blocked, or not valid JSON."""
    pass


class GeminiTimeoutError(GeminiError):
    """Raised when request times out after bounded retries."""
    pass


class GeminiUnavailableError(GeminiError):
    """Raised when the service is temporarily unavailable (HTTP 500/502/503/504 or network failure)."""
    pass


class GeminiClient:
    """Client for generating grounded structured knowledge from Gemini models."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        initial_backoff: float = 1.0,
        max_backoff: float = 8.0,
    ):
        settings = get_settings()
        if api_key is None and settings.GEMINI_API_KEY:
            self._api_key = settings.GEMINI_API_KEY.get_secret_value().strip()
        else:
            self._api_key = api_key.strip() if api_key else None

        self._model = (model or settings.GEMINI_MODEL).strip()
        self._timeout = timeout if timeout is not None else settings.GEMINI_REQUEST_TIMEOUT
        self._max_retries = max_retries if max_retries is not None else settings.GEMINI_MAX_RETRIES
        self._initial_backoff = max(0.01, float(initial_backoff))
        self._max_backoff = max(self._initial_backoff, float(max_backoff))

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self._api_key)

    @property
    def model(self) -> str:
        """Return the configured model identifier."""
        return self._model

    @property
    def timeout(self) -> int:
        """Return the request timeout in seconds."""
        return self._timeout

    @property
    def max_retries(self) -> int:
        """Return the maximum retry count."""
        return self._max_retries

    def generate_structured_json(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a prompt to Gemini requesting structured JSON output with bounded retries.
        
        Args:
            prompt: User prompt content containing bounded repository context.
            system_instruction: Optional high-level system directives.
            temperature: Sampling temperature (low for deterministic factual synthesis).
            response_schema: Optional native JSON schema to enforce on the Gemini output.
            
        Returns:
            Parsed JSON object as a Python dict.
            
        Raises:
            GeminiAuthError on missing/invalid credentials (HTTP 401/403).
            GeminiModelNotFoundError if model is not found (HTTP 404).
            GeminiQuotaError if rate limit or quota exceeded after retries (HTTP 429).
            GeminiTimeoutError on connection or socket timeouts after retries.
            GeminiUnavailableError on transient 5xx/network errors after retries.
            GeminiResponseError on malformed, blocked, or non-JSON output.
            GeminiError on unhandled permanent client errors.
        """
        if not self._api_key:
            raise GeminiAuthError(
                "GEMINI_API_KEY is not configured. Please set a valid API key in your environment or .env file."
            )

        endpoint_url = f"{GEMINI_API_HOST}/{self._model}:generateContent"

        gen_config: Dict[str, Any] = {
            "responseMimeType": "application/json",
            "temperature": temperature,
        }
        if response_schema:
            gen_config["responseSchema"] = response_schema

        request_body: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": gen_config,
        }

        if system_instruction:
            request_body["systemInstruction"] = {
                "parts": [{"text": system_instruction}],
            }

        post_data = json.dumps(request_body).encode("utf-8")

        req = urllib.request.Request(
            url=endpoint_url,
            data=post_data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "RelayPoint-MVP",
                "x-goog-api-key": self._api_key,
            },
        )

        last_error = None
        for attempt in range(self._max_retries + 1):
            start_time = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    resp_bytes = resp.read()
                    elapsed = time.monotonic() - start_time
                    logger.debug(
                        "Gemini request succeeded (model=%s, elapsed=%.2fs, attempt=%d/%d)",
                        self._model,
                        elapsed,
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    data = json.loads(resp_bytes.decode("utf-8"))
                    return self._extract_json_payload(data)

            except urllib.error.HTTPError as http_err:
                code = http_err.code
                last_error = http_err

                # Permanent client errors: fail immediately without retry
                if code in (401, 403):
                    logger.warning("Gemini API authentication failed (HTTP %d). Check GEMINI_API_KEY.", code)
                    raise GeminiAuthError("Gemini API key is invalid or unauthorized.") from http_err
                elif code == 404:
                    logger.warning("Configured Gemini model '%s' not found (HTTP 404).", self._model)
                    raise GeminiModelNotFoundError(
                        f"Configured Gemini model '{self._model}' was not found. Check GEMINI_MODEL setting."
                    ) from http_err
                elif code == 400:
                    logger.warning("Gemini API rejected request with HTTP 400 (Bad Request).")
                    raise GeminiError("Gemini API rejected request with HTTP 400 (Bad Request). Check request format.", status_code=400) from http_err
                elif 400 <= code < 500 and code != 429:
                    logger.warning("Gemini API client error HTTP %d.", code)
                    raise GeminiError(f"Gemini API request failed with client error HTTP {code}.", status_code=code) from http_err

                # Transient errors: HTTP 429, 500, 502, 503, 504
                if attempt < self._max_retries:
                    backoff = min(self._initial_backoff * (2 ** attempt), self._max_backoff)
                    retry_after_hdr = http_err.headers.get("Retry-After") if hasattr(http_err, "headers") and http_err.headers else None
                    if retry_after_hdr:
                        try:
                            retry_after_sec = float(retry_after_hdr)
                            if 0 < retry_after_sec <= self._max_backoff:
                                backoff = retry_after_sec
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "Transient HTTP %d from Gemini (model '%s', attempt %d/%d). Retrying in %.1fs...",
                        code,
                        self._model,
                        attempt + 1,
                        self._max_retries + 1,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue

                # Exhausted retries for transient HTTP error
                if code == 429:
                    logger.error("Gemini API rate limit or quota exceeded after %d retries.", self._max_retries)
                    raise GeminiQuotaError(
                        f"Gemini API rate limit or quota exceeded after {self._max_retries} retries."
                    ) from http_err
                else:
                    logger.error("Gemini API service unavailable (HTTP %d) after %d retries.", code, self._max_retries)
                    raise GeminiUnavailableError(
                        f"Gemini API service temporarily unavailable (HTTP {code}) after {self._max_retries} retries.",
                        status_code=code,
                    ) from http_err

            except (urllib.error.URLError, TimeoutError, socket.timeout) as net_err:
                last_error = net_err
                is_timeout = isinstance(net_err, (TimeoutError, socket.timeout)) or (
                    isinstance(net_err, urllib.error.URLError)
                    and (
                        isinstance(net_err.reason, (TimeoutError, socket.timeout))
                        or "timed out" in str(net_err.reason).lower()
                    )
                )

                if attempt < self._max_retries:
                    backoff = min(self._initial_backoff * (2 ** attempt), self._max_backoff)
                    err_desc = "timeout" if is_timeout else "network error"
                    logger.warning(
                        "Gemini %s (attempt %d/%d). Retrying in %.1fs...",
                        err_desc,
                        attempt + 1,
                        self._max_retries + 1,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue

                if is_timeout:
                    logger.error("Gemini request timed out after %ds (%d retries).", self._timeout, self._max_retries)
                    raise GeminiTimeoutError(
                        f"Gemini API request timed out after {self._timeout}s ({self._max_retries} retries)."
                    ) from net_err
                else:
                    reason = getattr(net_err, "reason", str(net_err))
                    logger.error("Network error communicating with Gemini API after %d retries: %s", self._max_retries, reason)
                    raise GeminiUnavailableError(
                        f"Network error communicating with Gemini API: {reason}"
                    ) from net_err

        raise GeminiUnavailableError(f"Gemini request failed after {self._max_retries} retries: {last_error}")

    def _extract_json_payload(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and parse the JSON string from Gemini's candidate output structure."""
        candidates = response_data.get("candidates")
        if not candidates:
            feedback = response_data.get("promptFeedback", {})
            block_reason = feedback.get("blockReason", "Unknown")
            raise GeminiResponseError(f"Gemini did not return any candidate outputs. Reason: {block_reason}")

        first_candidate = candidates[0]
        finish_reason = first_candidate.get("finishReason")
        if finish_reason in ("SAFETY", "RECITATION"):
            raise GeminiResponseError(f"Gemini output was blocked due to: {finish_reason}")

        content_parts = first_candidate.get("content", {}).get("parts", [])
        if not content_parts:
            raise GeminiResponseError("Gemini response candidate contains no content parts.")

        text_content = content_parts[0].get("text", "").strip()
        if not text_content:
            raise GeminiResponseError("Gemini candidate content part is empty.")

        # Clean any potential leading/trailing markdown code ticks if returned
        if text_content.startswith("```json"):
            text_content = text_content[7:]
        elif text_content.startswith("```"):
            text_content = text_content[3:]
        if text_content.endswith("```"):
            text_content = text_content[:-3]
        text_content = text_content.strip()

        try:
            parsed = json.loads(text_content)
            if not isinstance(parsed, dict):
                raise GeminiResponseError(f"Expected JSON object from model, received {type(parsed).__name__}.")
            return parsed
        except json.JSONDecodeError as decode_err:
            raise GeminiResponseError(
                f"Gemini output was not valid JSON: {decode_err.msg}. Preview: {text_content[:200]}"
            ) from decode_err
