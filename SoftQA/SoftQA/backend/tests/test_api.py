"""API smoke tests (need requirements-dev.txt). Run from backend/: python -m pytest -q
AI/Semgrep/Docker are not required: those paths are asserted to degrade gracefully."""
import io, os, tempfile, time, zipfile

os.environ["AURA_DATA_DIR"] = tempfile.mkdtemp()
# No os.environ edits here: GEMINI_*/AURA_ENV_FILE isolation lives in tests/__init__.py and the `no_ai` fixture (conftest.py).

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.constants import EXPECTED_DEFAULT_MODEL  # noqa: E402

CODE = b"def avg(xs):\n    return sum(xs) / len(xs)\n"


def zip_bytes(entries):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
    return b.getvalue()


def test_status_reports_gemini_never_gpt(no_ai):
    with TestClient(app) as c:
        st = c.get("/api/system/status").json()
        assert st["ai_provider"] == "google_gemini" and st["ai_model"] == EXPECTED_DEFAULT_MODEL
        assert st["ai_configured"] is False and "GEMINI_API_KEY" in st["ai_message"]
        assert "gpt" not in str(st).lower()
        chk = c.post("/api/system/ai-check").json()
        assert chk["ok"] is False and chk["kind"] == "not_configured"


def test_flow_without_ai(no_ai):
    with TestClient(app) as c:
        st = c.get("/api/system/status").json()
        assert st["ai_configured"] is False
        r = c.post("/api/projects/upload", files={"file": ("calc.py", CODE)})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        a = c.post(f"/api/analysis/{pid}/start", json={"use_ai": True}).json()
        for _ in range(60):
            cur = c.get(f"/api/analysis/{a['id']}").json()
            if cur["status"] in ("completed", "failed"):
                break
            time.sleep(1)
        assert cur["status"] == "completed", cur
        assert any("AI analysis unavailable" in w for w in cur["warnings"])
        fs = c.get(f"/api/analysis/{a['id']}/findings").json()
        assert any(f["rule_id"] == "aura.division-by-variable" for f in fs)
        assert c.post(f"/api/tests/{a['id']}/generate").status_code == 503
        assert c.get(f"/api/reports/{a['id']}/export?format=json").status_code == 200
        assert c.post(f"/api/tests/{a['id']}/execute").status_code == 400  # nothing approved


def test_rejects_bad_uploads():
    with TestClient(app) as c:
        assert c.post("/api/projects/upload", files={"file": ("x.exe", b"MZ")}).status_code == 400
        assert c.post("/api/projects/upload", files={"file": ("e.zip", zip_bytes({"../evil.py": "x=1"}))}).status_code == 400
        assert c.post("/api/projects/upload", files={"file": ("e.zip", b"junk")}).status_code == 400
