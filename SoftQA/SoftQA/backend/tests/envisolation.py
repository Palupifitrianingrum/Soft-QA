"""Run code in a fresh Python process with a minimal, explicit environment (allow-list), so results cannot depend on
the developer's shell, Windows environment variables, or real backend/.env."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
# Only what Python itself needs to start (incl. Windows). Everything else, notably GEMINI_*, is dropped.
ALLOWED = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL")

PROBE = """
import json
from app.config import settings as s
from app.agents import llm
st = llm.ai_status()
try:
    llm.parse(dict, "s", "u"); kind = None
except llm.AIUnavailable as e:
    kind = e.kind
print(json.dumps({"key": s.gemini_api_key, "model": s.gemini_model, "found": s.env_file_found,
                  "configured": st["configured"], "provider": st["provider"], "message": st["message"], "parse_kind": kind}))
"""


def probe(env_file=None, extra=None) -> dict:
    """Load app.config + llm in an isolated process. env_file=None -> a path that does not exist (no .env at all)."""
    with tempfile.TemporaryDirectory(prefix="aura-iso-") as d:
        env = {k: os.environ[k] for k in ALLOWED if k in os.environ}
        env.update(AURA_ENV_FILE=str(env_file or Path(d) / "missing.env"), AURA_DATA_DIR=str(Path(d) / "data"), PYTHONIOENCODING="utf-8")
        env.update(extra or {})
        out = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, cwd=BACKEND, timeout=60)
    if out.returncode != 0:
        raise AssertionError(f"probe failed: {out.stderr}")
    return json.loads(out.stdout)
