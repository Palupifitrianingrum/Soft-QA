"""Runtime configuration, read from environment / backend/.env. No secrets are hardcoded."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# backend/.env is the single source of truth. override=True so a stale/empty variable already set in the
# shell or Windows environment cannot silently win over the file. AURA_ENV_FILE exists for tests only.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"  # keep in sync with .env.example, README and tests/constants.py (enforced by test_repo_hygiene)
ENV_FILE = Path(os.getenv("AURA_ENV_FILE") or (BASE_DIR / ".env"))
ENV_FILE_FOUND = ENV_FILE.is_file()
load_dotenv(ENV_FILE, override=True)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    env_file: str = str(ENV_FILE)
    env_file_found: bool = ENV_FILE_FOUND
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 10)
    data_dir: Path = Path(os.getenv("AURA_DATA_DIR", str(BASE_DIR / "data"))).resolve()
    database_url: str = os.getenv("DATABASE_URL", "").strip()
    cors_origins: tuple = tuple(o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip())
    sandbox_image: str = os.getenv("SANDBOX_IMAGE", "aura-qa-sandbox:latest")
    sandbox_timeout: int = _int("SANDBOX_TIMEOUT_SECONDS", 60)
    sandbox_memory: str = os.getenv("SANDBOX_MEMORY", "512m")
    sandbox_cpus: str = os.getenv("SANDBOX_CPUS", "1")
    semgrep_registry: tuple = tuple(c.strip() for c in os.getenv("SEMGREP_REGISTRY_CONFIGS", "p/python,p/owasp-top-ten,p/secrets").split(",") if c.strip())
    rules_dir: Path = BASE_DIR / "rules"
    sandbox_dir: Path = BASE_DIR / "sandbox"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
