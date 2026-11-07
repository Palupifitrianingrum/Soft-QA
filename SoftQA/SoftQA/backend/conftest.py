"""pytest bootstrap. Importing `tests` runs tests/__init__.py, which strips GEMINI_*/AURA_* variables and points
AURA_ENV_FILE at a non-existent file BEFORE app.config is imported (conftest.py loads before any test module)."""
import dataclasses
import os

import pytest

import tests  # noqa: F401  (side effect: environment isolation)
from tests.constants import EXPECTED_DEFAULT_MODEL


@pytest.fixture
def no_ai(monkeypatch):
    """Explicitly 'no AI configured': empty key, no .env file, default model. Settings are restored after the test.
    Does not touch os.environ, the real backend/.env or production code."""
    from app.agents import llm
    from app.config import settings
    monkeypatch.setattr(llm, "settings", dataclasses.replace(
        settings, gemini_api_key="", gemini_model=EXPECTED_DEFAULT_MODEL,
        env_file=os.path.join(os.environ.get("AURA_DATA_DIR", ""), "no-such.env"), env_file_found=False))
    yield
