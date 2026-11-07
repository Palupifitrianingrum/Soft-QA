"""Test-suite isolation. This file runs BEFORE any test module imports `app.config`, in both unittest and pytest,
so the suite can never read a developer's real backend/.env or inherit GEMINI_*/AURA_* variables from the shell or
the Windows environment (which would otherwise change defaults, flip `configured`, or even trigger real API calls)."""
import os
import tempfile

_ISOLATION_DIR = tempfile.mkdtemp(prefix="aura-tests-")
_CONFIG_VARS = ("DATABASE_URL", "MAX_UPLOAD_MB", "CORS_ORIGINS", "SANDBOX_IMAGE", "SANDBOX_TIMEOUT_SECONDS",
                "SANDBOX_MEMORY", "SANDBOX_CPUS", "SEMGREP_REGISTRY_CONFIGS")
for _k in [k for k in os.environ if k.startswith(("GEMINI", "AURA_")) or k in _CONFIG_VARS]:
    del os.environ[_k]
os.environ["AURA_ENV_FILE"] = os.path.join(_ISOLATION_DIR, "no-such.env")  # points at a file that does not exist
os.environ["AURA_DATA_DIR"] = os.path.join(_ISOLATION_DIR, "data")
