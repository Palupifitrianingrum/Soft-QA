"""Guards against a half-finished provider migration: no legacy provider code, config or docs may remain."""
import re
import unittest
from pathlib import Path

from tests.constants import EXPECTED_DEFAULT_MODEL

ROOT = Path(__file__).resolve().parents[2]
# Built from fragments so this file does not match its own scan.
LEGACY = re.compile("open" + "ai|gp" + "t-[0-9]|chat" + "gpt", re.I)
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "data", ".venv", "dist"}
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".json", ".md", ".txt", ".yml", ".yaml", ".example", ".html", ".css", ".toml", ""}


def repo_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.suffix in TEXT_EXT:
            yield p


class HygieneTests(unittest.TestCase):
    def test_no_legacy_provider_references_anywhere(self):
        hits = [f"{p.relative_to(ROOT)}:{i}" for p in repo_files() for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1) if LEGACY.search(line)]
        self.assertEqual(hits, [])

    def test_dependencies(self):
        reqs = (ROOT / "backend/requirements.txt").read_text().lower()
        self.assertIn("google-genai", reqs)
        self.assertNotIn("open" + "ai", reqs)

    def test_env_example_declares_gemini_vars(self):
        env = (ROOT / ".env.example").read_text()
        self.assertRegex(env, r"(?m)^GEMINI_API_KEY=$")
        self.assertRegex(env, r"(?m)^GEMINI_MODEL=" + re.escape(EXPECTED_DEFAULT_MODEL) + "$")

    def test_model_default_is_consistent_everywhere(self):
        import re as _re
        cfg = (ROOT / "backend/app/config.py").read_text()
        self.assertRegex(cfg, r'(?m)^DEFAULT_GEMINI_MODEL = "' + _re.escape(EXPECTED_DEFAULT_MODEL) + '"')
        self.assertIn("or DEFAULT_GEMINI_MODEL", cfg)
        readme = (ROOT / "README.md").read_text()
        stale = _re.findall(r"gemini-\d[\w.]*-flash", readme)
        self.assertTrue(stale and set(stale) == {EXPECTED_DEFAULT_MODEL}, stale)

    def test_env_files_are_gitignored(self):
        ignore = (ROOT / ".gitignore").read_text().splitlines()
        self.assertIn(".env", ignore)

    def test_no_hardcoded_key_literals(self):
        for p in repo_files():
            if p.name == "test_llm.py" or p.name == "test_ai_config.py":
                continue
            self.assertIsNone(re.search(r"AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,}", p.read_text(errors="ignore")), p)

    def test_ai_calls_only_go_through_gemini_wrapper(self):
        for name in ("reviewer.py", "test_engineer.py"):
            src = (ROOT / "backend/app/agents" / name).read_text()
            self.assertIn("llm.parse(", src)
            self.assertNotIn("import requests", src)
            self.assertNotIn("http", src.lower().replace("https://", "x"))


if __name__ == "__main__":
    unittest.main()
