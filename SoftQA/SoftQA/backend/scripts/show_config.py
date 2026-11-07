#!/usr/bin/env python
"""Prints which .env the backend would read and where each Gemini setting comes from. Never prints the API key.
Run from backend/ with the venv active:   python scripts\\show_config.py
(It reads the same way app/config.py does: backend/.env, overriding shell variables.)"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
shell_model, shell_key = os.environ.get("GEMINI_MODEL"), os.environ.get("GEMINI_API_KEY")
shell_env_file = os.environ.get("AURA_ENV_FILE")
from app import config  # noqa: E402  (loading it applies backend/.env with override=True)
from dotenv import dotenv_values  # noqa: E402

s = config.settings
print("python executable      :", sys.executable)
print("config.py loaded from  :", Path(config.__file__).resolve())
print("env file path used     :", s.env_file, "(AURA_ENV_FILE is set in this shell!)" if shell_env_file else "")
print("env file exists        :", s.env_file_found)
vals = dotenv_values(s.env_file) if s.env_file_found else {}
print("GEMINI_MODEL in file   :", repr(vals.get("GEMINI_MODEL")) if "GEMINI_MODEL" in vals else "(not present)")
print("GEMINI_MODEL in shell  :", repr(shell_model) if shell_model is not None else "(not set)", "-> overridden by the file" if shell_model and vals.get("GEMINI_MODEL") else "")
print("effective model        :", s.gemini_model, "<- from file" if vals.get("GEMINI_MODEL", "").strip() else "<- code default (DEFAULT_GEMINI_MODEL)")
print("GEMINI_API_KEY in file :", "present, %d chars" % len(vals.get("GEMINI_API_KEY", "")) if vals.get("GEMINI_API_KEY") else "empty/absent")
print("effective key present  :", bool(s.gemini_api_key))
for name in (".env", ".env.txt"):
    p = config.BASE_DIR / name
    print(f"{name:<22} :", "exists" if p.exists() else "missing", "-", p)
