"""Gemini configuration, status, live-check and schema tests. Uses a scripted fake `google-genai`; the real SDK/API is not called."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agents import llm
from tests.constants import EXPECTED_DEFAULT_MODEL
from tests.envisolation import probe
from tests.test_llm import CFG, KEY, APIError, ConnectError, fake_sdk, ok

BACKEND = Path(__file__).resolve().parent.parent
LEGACY = "OPEN" + "AI"
try:
    import pydantic  # noqa: F401
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


def run_cfg(env_extra, env_file=None):
    """Resolved config in a fresh, allow-listed process (see tests/envisolation.py)."""
    got = probe(env_file=env_file, extra=env_extra)
    return {"key": got["key"], "model": got["model"], "found": got["found"]}


class SuiteIsolationTests(unittest.TestCase):
    def test_suite_cannot_see_local_env_or_shell_config(self):
        from app.config import settings
        self.assertFalse(settings.env_file_found); self.assertEqual(settings.gemini_api_key, "")
        self.assertEqual(settings.gemini_model, EXPECTED_DEFAULT_MODEL)
        self.assertNotEqual(Path(settings.env_file).resolve(), (BACKEND / ".env").resolve())
        self.assertFalse([k for k in os.environ if k.startswith("GEMINI")])


class ConfigTests(unittest.TestCase):
    def test_defaults_when_nothing_configured(self):
        self.assertEqual(run_cfg({}), {"key": "", "model": EXPECTED_DEFAULT_MODEL, "found": False})

    def test_values_loaded_from_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"; f.write_text("GEMINI_API_KEY=abc123\nGEMINI_MODEL=gemini-2.5-pro\n")
            self.assertEqual(run_cfg({}, f), {"key": "abc123", "model": "gemini-2.5-pro", "found": True})

    def test_env_file_beats_stale_or_empty_shell_variables(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"; f.write_text("GEMINI_API_KEY=fromfile\nGEMINI_MODEL=gemini-2.5-pro\n")
            got = run_cfg({"GEMINI_API_KEY": "", "GEMINI_MODEL": "stale-model"}, f)
            self.assertEqual((got["key"], got["model"]), ("fromfile", "gemini-2.5-pro"))

    def test_legacy_provider_variables_cannot_influence_config(self):
        got = run_cfg({LEGACY + "_API_KEY": "sk-legacy", LEGACY + "_MODEL": "gp" + "t-4.1-mini"})
        self.assertEqual((got["key"], got["model"]), ("", EXPECTED_DEFAULT_MODEL))

    def test_blank_model_falls_back_to_default(self):
        self.assertEqual(run_cfg({"GEMINI_MODEL": "  "})["model"], EXPECTED_DEFAULT_MODEL)


class StatusTests(unittest.TestCase):
    def status(self, cfg=CFG, mods=None):
        with patch.object(llm, "settings", cfg), patch.dict(sys.modules, mods if mods is not None else fake_sdk([], [])):
            return llm.ai_status()

    def test_not_configured_has_diagnostic(self):
        s = self.status(SimpleNamespace(gemini_api_key="", gemini_model=EXPECTED_DEFAULT_MODEL, env_file="C:/x/.env", env_file_found=False))
        self.assertFalse(s["configured"]); self.assertIn("GEMINI_API_KEY", s["message"]); self.assertIn("NOT found", s["message"])
        self.assertEqual((s["provider"], s["model"]), ("google_gemini", EXPECTED_DEFAULT_MODEL))

    def test_key_but_sdk_missing_is_not_configured(self):
        s = self.status(mods={"google": None})
        self.assertFalse(s["configured"]); self.assertIn("google-genai", s["message"])

    def test_key_but_client_cannot_initialise_is_not_configured(self):
        mods = fake_sdk([], [])
        def boom(**kw): raise ValueError(f"bad init with {KEY}")
        mods["google.genai"].Client = boom
        s = self.status(mods=mods)
        self.assertFalse(s["configured"]); self.assertNotIn(KEY, s["message"])

    def test_configured_when_client_initialises(self):
        s = self.status()
        self.assertTrue(s["configured"]); self.assertEqual(s["model"], EXPECTED_DEFAULT_MODEL)
        self.assertNotIn("gpt", json.dumps(s).lower()); self.assertNotIn(KEY, json.dumps(s))


class CheckAndErrorTests(unittest.TestCase):
    def run_check(self, outcomes, cfg=CFG):
        calls = []
        with patch.object(llm, "settings", cfg), patch.object(llm, "_sleep", lambda s: None), patch.dict(sys.modules, fake_sdk(outcomes, calls)):
            return llm.check(), calls

    def test_check_success_makes_one_plain_request(self):
        res, calls = self.run_check([SimpleNamespace(text="OK", parsed=None, candidates=[], prompt_feedback=None)])
        self.assertTrue(res["ok"]); self.assertEqual(res["reply"], "OK"); self.assertEqual(res["model"], EXPECTED_DEFAULT_MODEL)
        cfg = [c for c in calls if c[0] == "call"][0][1]["config"]
        self.assertFalse(hasattr(cfg, "response_schema"))  # connectivity check is not schema-constrained

    def test_check_reports_failures_without_raising_or_leaking(self):
        res, _ = self.run_check([APIError(400, f"API key not valid {KEY}", "INVALID_ARGUMENT")])
        self.assertEqual((res["ok"], res["kind"]), (False, "invalid_key")); self.assertNotIn(KEY, json.dumps(res))
        res, _ = self.run_check([], SimpleNamespace(gemini_api_key="", gemini_model="m"))
        self.assertEqual(res["kind"], "not_configured")

    def test_schema_incompatibility_detected_client_side_and_not_retried(self):
        calls = []
        mods = fake_sdk([], calls)
        def bad_cfg(**kw): raise ValueError("Unsupported schema type for response_schema")
        mods["google.genai.types"].GenerateContentConfig = bad_cfg
        with patch.object(llm, "settings", CFG), patch.dict(sys.modules, mods):
            with self.assertRaises(llm.AIUnavailable) as cm:
                llm.parse(dict, "s", "u")
        self.assertEqual(cm.exception.kind, "schema_incompatible"); self.assertFalse([c for c in calls if c[0] == "call"])

    def test_network_errors_are_retried_as_temporary(self):
        calls, sleeps = [], []
        with patch.object(llm, "settings", CFG), patch.object(llm, "_sleep", sleeps.append), patch.dict(sys.modules, fake_sdk([ConnectError("dns")] * 3, calls)):
            with self.assertRaises(llm.AIUnavailable) as cm:
                llm.parse(dict, "s", "u")
        self.assertEqual((cm.exception.kind, sleeps), ("network_error", [2, 6]))
        calls = []
        with patch.object(llm, "settings", CFG), patch.object(llm, "_sleep", lambda s: None), patch.dict(sys.modules, fake_sdk([ConnectionError("reset"), ok(text='{"v": 1}')], calls)):
            class M:
                @classmethod
                def model_validate_json(cls, t): return "parsed"
            self.assertEqual(llm.parse(M, "s", "u"), "parsed")

    def test_invalid_key_and_quota_are_never_retried(self):
        for exc in (APIError(401, "bad key", "UNAUTHENTICATED"), APIError(429, "quota exceeded", "RESOURCE_EXHAUSTED"), APIError(404, "no model", "NOT_FOUND")):
            res, calls = self.run_check([exc])
            self.assertEqual(len([c for c in calls if c[0] == "call"]), 1, exc)


@unittest.skipUnless(HAS_PYDANTIC, "pydantic not installed in this environment; run on your machine")
class RealSchemaTests(unittest.TestCase):
    """JSON from (fake) Gemini is parsed into the project's REAL Pydantic schemas, unchanged from before the migration."""

    def test_reviewer_pipeline_validates_lines_and_evidence(self):
        from app.agents import reviewer
        src = "def avg(xs):\\n    return sum(xs) / len(xs)\\n".replace("\\n", "\n")
        payload = {"findings": [
            {"title": "Division by zero", "severity": "high", "category": "runtime", "line_start": 2, "line_end": 2, "description": "d",
             "evidence": "return sum(xs) / len(xs)", "recommendation": "guard", "confidence": 0.9},
            {"title": "Invented", "severity": "low", "category": "logic", "line_start": 99, "line_end": 99, "description": "d",
             "evidence": "x", "recommendation": "r", "confidence": 0.9},
            {"title": "Wrong quote", "severity": "low", "category": "logic", "line_start": 1, "line_end": 1, "description": "d",
             "evidence": "totally different", "recommendation": "r", "confidence": 0.95}],
            "insufficient_evidence": ""}
        with patch.object(llm, "settings", CFG), patch.dict(sys.modules, fake_sdk([ok(text=json.dumps(payload))], [])):
            found, dropped, _ = reviewer.review_file("calc.py", src, [])
        self.assertEqual(dropped, 1); self.assertEqual([f.line_start for f in found], [2, 1])
        self.assertTrue(found[0].evidence_verified); self.assertFalse(found[1].evidence_verified); self.assertLessEqual(found[1].confidence, 0.4)
        self.assertTrue(all(f.source == "ai" and f.status == "potential" for f in found))

    def test_test_engineer_schema(self):
        from app.agents import test_engineer
        payload = {"tests": [{"test_name": "zero", "description": "d", "test_type": "exception", "input_json": "{}", "expected_result": "raises",
                              "priority": "high", "target_file": "calc.py", "code": "import pytest\ndef test_x():\n    assert True\n"}]}
        with patch.object(llm, "settings", CFG), patch.dict(sys.modules, fake_sdk([ok(text=json.dumps(payload))], [])):
            tests = test_engineer.generate([("calc.py", "x = 1\n")], [])
        self.assertEqual((len(tests), tests[0].test_type, tests[0].priority), (1, "exception", "high"))

    def test_malformed_json_for_real_schema_is_bad_response(self):
        from app.agents.reviewer import AIReview
        with patch.object(llm, "settings", CFG), patch.dict(sys.modules, fake_sdk([ok(text='{"findings": "nope"}')], [])):
            with self.assertRaises(llm.AIUnavailable) as cm:
                llm.parse(AIReview, "s", "u")
        self.assertEqual(cm.exception.kind, "bad_response")


if __name__ == "__main__":
    unittest.main()


class NetworkDiagnosticsTests(unittest.TestCase):
    """Network failures must explain WHY (root cause) without leaking the key, and must not be retried when pointless."""

    def run_parse(self, outcomes):
        calls, sleeps = [], []
        with patch.object(llm, "settings", CFG), patch.object(llm, "_sleep", sleeps.append), patch.dict(sys.modules, fake_sdk(outcomes, calls)):
            try:
                llm.parse(dict, "s", "u")
            except llm.AIUnavailable as exc:
                return exc, len([c for c in calls if c[0] == "call"]), sleeps
        self.fail("expected AIUnavailable")

    def test_network_error_reports_root_cause_and_chain(self):
        e = ConnectError("All connection attempts failed"); e.__cause__ = OSError(f"[Errno 11001] getaddrinfo failed (key={KEY})")
        err, calls, sleeps = self.run_parse([e, e, e])
        self.assertEqual((err.kind, calls, sleeps), ("network_error", 3, [2, 6]))  # temporary -> retried
        self.assertIn("getaddrinfo failed", str(err)); self.assertIn("diagnose_gemini.py", str(err))
        self.assertEqual(err.detail[0].split(":")[0], "ConnectError"); self.assertEqual(err.detail[-1].split(":")[0], "OSError")
        self.assertNotIn(KEY, str(err) + " ".join(err.detail))

    def test_certificate_errors_are_classified_and_not_retried(self):
        import ssl
        e = ConnectError("tls"); e.__cause__ = ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer certificate")
        err, calls, sleeps = self.run_parse([e])
        self.assertEqual((err.kind, calls, sleeps), ("tls_error", 1, [])); self.assertIn("SSL_CERT_FILE", str(err))
        err, calls, _ = self.run_parse([ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in chain")])
        self.assertEqual((err.kind, calls), ("tls_error", 1))

    def test_check_exposes_detail_for_the_ui_and_scripts(self):
        e = ConnectError("refused"); e.__cause__ = OSError("[WinError 10061] No connection could be made")
        with patch.object(llm, "settings", CFG), patch.object(llm, "_sleep", lambda s: None), patch.dict(sys.modules, fake_sdk([e] * 3, [])):
            res = llm.check()
        self.assertEqual((res["ok"], res["kind"]), (False, "network_error")); self.assertIn("WinError 10061", " ".join(res["detail"]))

    def test_diagnose_script_masks_proxy_credentials(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("diagnose_gemini", BACKEND / "scripts" / "diagnose_gemini.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        masked = mod.mask_proxy("http://user:s3cret@proxy.corp:8080")
        self.assertEqual(masked, "http://proxy.corp:8080"); self.assertNotIn("s3cret", masked)
        self.assertEqual(mod.mask_proxy("proxy.corp:3128"), "http://proxy.corp:3128")
