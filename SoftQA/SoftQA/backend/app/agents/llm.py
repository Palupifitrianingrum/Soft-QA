"""Google Gemini wrapper (official `google-genai` SDK) with schema-constrained JSON output.

`parse(Model, system, user)` returns a validated Pydantic instance, or raises AIUnavailable with a user-presentable
message and a machine-readable `kind`. The SDK is imported lazily so the whole app (static analysis, security
scanning, uploads, reports) works with no key and even with `google-genai` not installed.
API keys are never logged or put in messages (see _redact).
"""
from __future__ import annotations

import ssl
import time
from typing import TypeVar

from ..config import settings

T = TypeVar("T")
PROVIDER = "google_gemini"
REQUEST_TIMEOUT_MS = 120_000
BACKOFF_SECONDS = (2, 6)  # waits between the (up to) 3 attempts
RETRYABLE = {"rate_limited", "server_error", "timeout", "network_error"}  # never: quota, auth, schema, model, blocked
_sleep = time.sleep  # indirection so tests do not really wait


class AIUnavailable(Exception):
    """AI feature cannot be used right now. `kind` is one of: not_configured, sdk_missing, invalid_key,
    permission_denied, quota_exceeded, rate_limited, model_not_found, schema_incompatible, bad_request,
    server_error, network_error, tls_error, timeout, blocked, truncated, bad_response, request_failed."""

    def __init__(self, message: str, kind: str = "request_failed", detail: list[str] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.detail = detail or []  # redacted exception chain, outermost first (for diagnosing network problems)


def _redact(text: str) -> str:
    key = settings.gemini_api_key
    return text.replace(key, "***") if key else text


def ai_status() -> dict:
    """What the app can ACTUALLY do right now. 'configured' = key present AND the SDK is installed AND a client
    can be constructed. The key itself is only validated by Google on the first request (see check())."""
    base = {"provider": PROVIDER, "model": settings.gemini_model}
    key = settings.gemini_api_key
    if not key:
        where = getattr(settings, "env_file", "backend/.env")
        found = "found" if getattr(settings, "env_file_found", False) else "NOT found"
        return {**base, "configured": False,
                "message": f"GEMINI_API_KEY is empty. Config file {where} was {found}. Set the key there and restart the backend."}
    try:
        from google import genai
    except ImportError:
        return {**base, "configured": False, "message": "GEMINI_API_KEY is set but the 'google-genai' package is not installed (pip install -r requirements.txt)."}
    try:
        genai.Client(api_key=key)
    except Exception as exc:  # noqa: BLE001
        return {**base, "configured": False, "message": f"Gemini client could not be initialised ({type(exc).__name__}): {_redact(str(exc))[:200]}"}
    return {**base, "configured": True,
            "message": "Gemini client initialised. Google validates the key on the first request; POST /api/system/ai-check performs a live test."}


def ai_configured() -> bool:
    return ai_status()["configured"]


def _classify_api_error(exc: Exception) -> AIUnavailable:
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    msg = _redact(str(getattr(exc, "message", "") or exc))[:300]
    low = msg.lower()
    if code == 401 or status == "UNAUTHENTICATED" or ("api key" in low and any(w in low for w in ("not valid", "invalid", "expired"))):
        return AIUnavailable("Gemini rejected the API key (invalid or expired). Check GEMINI_API_KEY in backend/.env.", "invalid_key")
    if code == 403 or status == "PERMISSION_DENIED":
        return AIUnavailable(f"Gemini denied access: the key lacks permission, the API is not enabled for it, or the region is unsupported. ({msg})", "permission_denied")
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        if any(w in low for w in ("quota", "billing", "per day", "free tier")):
            return AIUnavailable(f"Gemini quota exhausted for this key/project. Wait for the quota to reset, or enable billing / use another key. ({msg})", "quota_exceeded")
        return AIUnavailable(f"Gemini rate limit hit (too many requests). Retry in a minute. ({msg})", "rate_limited")
    if code == 404 or status == "NOT_FOUND":
        return AIUnavailable(f"Gemini model '{settings.gemini_model}' was not found or is not available to this key. Check GEMINI_MODEL. ({msg})", "model_not_found")
    if code == 400 or status in ("INVALID_ARGUMENT", "FAILED_PRECONDITION"):
        if "schema" in low:
            return AIUnavailable(f"Gemini does not accept the response schema for this model: {msg}", "schema_incompatible")
        return AIUnavailable(f"Gemini rejected the request: {msg}", "bad_request")
    if (isinstance(code, int) and code >= 500) or status in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"):
        return AIUnavailable(f"Gemini service error or overload ({code or status}). Try again shortly. ({msg})", "server_error")
    return AIUnavailable(f"Gemini API error ({code or status or type(exc).__name__}): {msg}", "request_failed")


def _iter_exc(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen and len(seen) < 6:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _chain(exc: BaseException) -> list[str]:
    """Redacted 'Type: message' for the exception and its causes. The root cause (last) is what explains a network failure."""
    return [f"{type(e).__name__}: {_redact(str(getattr(e, 'message', None) or e))[:160]}" for e in _iter_exc(exc)]


_DIAG = r"Run backend\scripts\diagnose_gemini.py for a step-by-step network diagnosis."


def _classify_generic(exc: Exception) -> AIUnavailable:
    chain = _chain(exc)
    root, blob = chain[-1], " ".join(chain).lower()
    names = " ".join(type(e).__name__.lower() for e in _iter_exc(exc))
    if any(isinstance(e, ssl.SSLError) for e in _iter_exc(exc)) or "certificate_verify_failed" in blob or "[ssl" in blob:
        return AIUnavailable(f"TLS/certificate error while contacting Gemini ({root}). A proxy, antivirus or corporate firewall may be "
                             f"intercepting HTTPS; point SSL_CERT_FILE at your CA bundle. {_DIAG}", "tls_error", chain)
    if "timeout" in names or isinstance(exc, TimeoutError):
        return AIUnavailable(f"The request to Gemini timed out ({root}). {_DIAG}", "timeout", chain)
    if "connect" in names or "network" in names or isinstance(exc, ConnectionError):
        return AIUnavailable(f"Could not reach Gemini (network error: {root}). Check internet access, DNS, VPN, proxy and firewall. {_DIAG}", "network_error", chain)
    if isinstance(exc, (ValueError, TypeError)) and "schema" in str(exc).lower():
        return AIUnavailable(f"The response schema is not supported by the Gemini SDK/model: {_redact(str(exc))[:200]}", "schema_incompatible", chain)
    return AIUnavailable(f"Could not complete the Gemini request ({type(exc).__name__}): {_redact(str(exc))[:300]}", "request_failed", chain)


def _finish_reason(resp) -> str:
    cands = getattr(resp, "candidates", None) or []
    return str(getattr(cands[0], "finish_reason", "") or "") if cands else ""


def _extract(resp, model_cls):
    parsed = getattr(resp, "parsed", None)
    if parsed is not None and isinstance(parsed, model_cls):
        return parsed
    text = getattr(resp, "text", None)
    fr = _finish_reason(resp).upper()
    if text:
        try:
            return model_cls.model_validate_json(text)
        except Exception as exc:  # noqa: BLE001 - invalid / truncated JSON
            if "MAX_TOKENS" in fr:
                raise AIUnavailable("Gemini's answer was cut off (output limit reached). Try fewer/smaller files.", "truncated") from exc
            raise AIUnavailable(f"Gemini returned JSON that does not match the expected schema: {_redact(str(exc))[:200]}", "bad_response") from exc
    reason = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
    if reason or any(w in fr for w in ("SAFETY", "BLOCKLIST", "PROHIBITED", "RECITATION")):
        raise AIUnavailable(f"Gemini blocked this content ({reason or fr}).", "blocked")
    if "MAX_TOKENS" in fr:
        raise AIUnavailable("Gemini's answer was cut off (output limit reached).", "truncated")
    raise AIUnavailable("Gemini returned an empty response.", "bad_response")


def _generate(system: str, user: str, schema=None):
    """One Gemini call with classification + bounded retries of TEMPORARY errors only. Returns the SDK response."""
    key = settings.gemini_api_key
    if not key:
        raise AIUnavailable("GEMINI_API_KEY is not set. Add it to backend/.env to enable AI analysis (see README).", "not_configured")
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:
        raise AIUnavailable("The 'google-genai' package is not installed (pip install -r requirements.txt).", "sdk_missing") from exc
    try:
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
        kwargs = {"system_instruction": system, "temperature": 0.2}
        if schema is not None:
            kwargs.update(response_mime_type="application/json", response_schema=schema)
        config = types.GenerateContentConfig(**kwargs)
    except Exception as exc:  # noqa: BLE001 - e.g. schema the SDK cannot convert
        raise _classify_generic(exc) from exc
    attempts = len(BACKOFF_SECONDS) + 1
    for attempt in range(attempts):
        try:
            return client.models.generate_content(model=settings.gemini_model, contents=user, config=config)
        except errors.APIError as exc:
            err, cause = _classify_api_error(exc), exc
        except Exception as exc:  # noqa: BLE001 - network/timeouts/SDK internals
            err, cause = _classify_generic(exc), exc
        if err.kind in RETRYABLE and attempt < attempts - 1:
            _sleep(BACKOFF_SECONDS[attempt])
            continue
        raise err from cause
    raise AIUnavailable("Gemini request failed.", "request_failed")  # unreachable


def parse(model_cls: type[T], system: str, user: str) -> T:
    """Schema-constrained call; result validated into the given Pydantic model."""
    return _extract(_generate(system, user, model_cls), model_cls)


def check() -> dict:
    """Live connectivity test: one tiny real request. Never raises; never includes the key."""
    base = {"provider": PROVIDER, "model": settings.gemini_model}
    start = time.monotonic()
    try:
        resp = _generate("You are a connectivity check.", "Reply with the single word OK.")
    except AIUnavailable as exc:
        return {**base, "ok": False, "kind": exc.kind, "message": str(exc), "detail": exc.detail}
    return {**base, "ok": True, "kind": "ok", "latency_ms": round((time.monotonic() - start) * 1000),
            "message": "Gemini responded.", "reply": str(getattr(resp, "text", "") or "")[:40]}
