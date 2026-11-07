"""Tests for the Gemini wrapper using a scripted fake of the `google-genai` SDK (the real SDK is not required).
They verify OUR request construction, response parsing, error classification, retries and key redaction.
They cannot prove the real Gemini service accepts the request: see README 'Verification status'."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from app.agents import llm
from tests.constants import EXPECTED_DEFAULT_MODEL
from tests.envisolation import probe

KEY = "AIza-SECRET-KEY-123"
CFG = SimpleNamespace(gemini_api_key=KEY, gemini_model=EXPECTED_DEFAULT_MODEL)


class Model:  # stand-in for a Pydantic model
    def __init__(self, v): self.v = v

    @classmethod
    def model_validate_json(cls, text):
        return cls(json.loads(text)["v"])


class APIError(Exception):  # mirrors google.genai.errors.APIError attributes
    def __init__(self, code, message, status=""):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class ReadTimeout(Exception):
    pass


class ConnectError(Exception):
    pass


def fake_sdk(outcomes, calls):
    """outcomes: list of exceptions (raised) or responses (returned), consumed one per call."""
    errors = ModuleType("google.genai.errors"); errors.APIError = APIError
    types_ = ModuleType("google.genai.types")
    types_.GenerateContentConfig = lambda **kw: SimpleNamespace(**kw)
    types_.HttpOptions = lambda **kw: SimpleNamespace(**kw)

    class Client:
        def __init__(self, api_key=None, http_options=None):
            calls.append(("init", api_key, http_options))
            self.models = SimpleNamespace(generate_content=self.generate)

        def generate(self, **kw):
            calls.append(("call", kw))
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return o

    genai = ModuleType("google.genai"); genai.Client, genai.errors, genai.types = Client, errors, types_
    google = ModuleType("google"); google.genai = genai
    return {"google": google, "google.genai": genai, "google.genai.errors": errors, "google.genai.types": types_}


def ok(parsed=None, text=None, finish="STOP", block=None):
    return SimpleNamespace(parsed=parsed, text=text, candidates=[SimpleNamespace(finish_reason=finish)],
                           prompt_feedback=SimpleNamespace(block_reason=block))


class GeminiTests(unittest.TestCase):
    def run_parse(self, outcomes, cfg=CFG):
        calls, sleeps = [], []
        with patch.object(llm, "settings", cfg), patch.object(llm, "_sleep", sleeps.append), \
                patch.dict(sys.modules, fake_sdk(outcomes, calls)):
            try:
                return llm.parse(Model, "SYS", "USER"), calls, sleeps, None
            except llm.AIUnavailable as exc:
                return None, calls, sleeps, exc

    def calls_made(self, calls):
        return [c for c in calls if c[0] == "call"]

    # ---- configuration / graceful degradation ----
    def test_missing_key_never_touches_sdk(self):
        with patch.object(llm, "settings", SimpleNamespace(gemini_api_key="", gemini_model="m")), \
                patch.dict(sys.modules, {"google": None}):  # SDK import would fail loudly if attempted
            with self.assertRaises(llm.AIUnavailable) as cm:
                llm.parse(Model, "s", "u")
            self.assertEqual(cm.exception.kind, "not_configured")
            self.assertIn("GEMINI_API_KEY", str(cm.exception))
            self.assertFalse(llm.ai_configured())

    def test_sdk_not_installed(self):
        with patch.object(llm, "settings", CFG), patch.dict(sys.modules, {"google": None}):
            with self.assertRaises(llm.AIUnavailable) as cm:
                llm.parse(Model, "s", "u")
            self.assertEqual(cm.exception.kind, "sdk_missing")

    def test_default_model_and_no_key_in_isolated_environment(self):
        """Fresh process, allow-listed env, AURA_ENV_FILE -> nonexistent temp file: never reads the developer's real backend/.env."""
        got = probe()
        self.assertEqual((got["model"], got["key"], got["found"]), (EXPECTED_DEFAULT_MODEL, "", False))
        self.assertFalse(got["configured"]); self.assertEqual(got["provider"], "google_gemini")
        self.assertEqual(got["parse_kind"], "not_configured"); self.assertIn("GEMINI_API_KEY", got["message"])

    def test_env_file_without_a_key_is_not_configured(self):
        for text in ("MAX_UPLOAD_MB=5\n", "GEMINI_API_KEY=\nGEMINI_MODEL=\n"):  # second = a freshly copied .env.example
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / ".env"; f.write_text(text)
                got = probe(env_file=f)
            self.assertEqual((got["found"], got["key"], got["configured"], got["parse_kind"]), (True, "", False, "not_configured"), text)
            self.assertEqual(got["model"], EXPECTED_DEFAULT_MODEL)

    def test_env_file_values_override_the_default_in_isolated_environment(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"; f.write_text("GEMINI_API_KEY=k\nGEMINI_MODEL=gemini-2.5-pro\n")
            got = probe(env_file=f)
        self.assertEqual((got["model"], bool(got["key"])), ("gemini-2.5-pro", True))

    # ---- success paths ----
    def test_request_shape_and_parsed_result(self):
        m = Model(1)
        res, calls, _, err = self.run_parse([ok(parsed=m)])
        self.assertIs(res, m); self.assertIsNone(err)
        init = calls[0]
        self.assertEqual(init[1], KEY); self.assertEqual(init[2].timeout, llm.REQUEST_TIMEOUT_MS)
        kw = self.calls_made(calls)[0][1]
        self.assertEqual(kw["model"], EXPECTED_DEFAULT_MODEL); self.assertEqual(kw["contents"], "USER")
        cfg = kw["config"]
        self.assertEqual((cfg.system_instruction, cfg.response_mime_type, cfg.response_schema), ("SYS", "application/json", Model))

    def test_falls_back_to_json_text(self):
        res, *_ = self.run_parse([ok(parsed=None, text='{"v": 7}')])
        self.assertEqual(res.v, 7)

    # ---- error handling ----
    def test_invalid_key_variants_no_retry(self):
        for exc in (APIError(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"),
                    APIError(401, "Request had invalid authentication credentials", "UNAUTHENTICATED")):
            _, calls, sleeps, err = self.run_parse([exc])
            self.assertEqual(err.kind, "invalid_key"); self.assertEqual(len(self.calls_made(calls)), 1); self.assertEqual(sleeps, [])
            self.assertIn("GEMINI_API_KEY", str(err)); self.assertNotIn(KEY, str(err))

    def test_permission_denied_and_model_not_found_and_bad_request(self):
        self.assertEqual(self.run_parse([APIError(403, "API not enabled", "PERMISSION_DENIED")])[3].kind, "permission_denied")
        e = self.run_parse([APIError(404, "models/foo is not found", "NOT_FOUND")])[3]
        self.assertEqual(e.kind, "model_not_found"); self.assertIn(EXPECTED_DEFAULT_MODEL, str(e))
        self.assertEqual(self.run_parse([APIError(400, "Unsupported schema", "INVALID_ARGUMENT")])[3].kind, "schema_incompatible")
        self.assertEqual(self.run_parse([APIError(400, "Bad field", "INVALID_ARGUMENT")])[3].kind, "bad_request")

    def test_quota_is_not_retried(self):
        _, calls, sleeps, err = self.run_parse([APIError(429, "You exceeded your current quota, check billing", "RESOURCE_EXHAUSTED")])
        self.assertEqual(err.kind, "quota_exceeded"); self.assertEqual(len(self.calls_made(calls)), 1); self.assertEqual(sleeps, [])

    def test_rate_limit_retries_then_gives_up(self):
        rl = lambda: APIError(429, "Too many requests", "RESOURCE_EXHAUSTED")  # noqa: E731
        _, calls, sleeps, err = self.run_parse([rl(), rl(), rl()])
        self.assertEqual(err.kind, "rate_limited"); self.assertEqual(len(self.calls_made(calls)), 3); self.assertEqual(sleeps, [2, 6])

    def test_transient_failure_recovers(self):
        m = Model(2)
        res, calls, sleeps, err = self.run_parse([APIError(503, "overloaded", "UNAVAILABLE"), m and ok(parsed=m)])
        self.assertIs(res, m); self.assertEqual(len(self.calls_made(calls)), 2); self.assertEqual(sleeps, [2])

    def test_server_error_exhausts_retries(self):
        _, calls, _, err = self.run_parse([APIError(500, "internal", "INTERNAL")] * 3)
        self.assertEqual((err.kind, len(self.calls_made(calls))), ("server_error", 3))

    def test_timeout_retried_and_other_errors_redact_key(self):
        _, calls, sleeps, err = self.run_parse([ReadTimeout("slow")] * 3)
        self.assertEqual((err.kind, len(self.calls_made(calls)), sleeps), ("timeout", 3, [2, 6]))
        _, calls, _, err = self.run_parse([RuntimeError(f"connection failed for key={KEY}")])
        self.assertEqual((err.kind, len(self.calls_made(calls))), ("request_failed", 1)); self.assertNotIn(KEY, str(err))

    def test_bad_responses(self):
        self.assertEqual(self.run_parse([ok(text="not json")])[3].kind, "bad_response")
        self.assertEqual(self.run_parse([ok(text='{"v": ', finish="MAX_TOKENS")])[3].kind, "truncated")
        self.assertEqual(self.run_parse([ok(finish="STOP", block="SAFETY")])[3].kind, "blocked")
        self.assertEqual(self.run_parse([ok(finish="SAFETY")])[3].kind, "blocked")
        self.assertEqual(self.run_parse([ok()])[3].kind, "bad_response")

    def test_errors_are_aiunavailable_so_callers_degrade(self):
        err = self.run_parse([APIError(429, "quota", "RESOURCE_EXHAUSTED")])[3]
        self.assertIsInstance(err, llm.AIUnavailable)  # pipeline/api catch this exact type


if __name__ == "__main__":
    unittest.main()
