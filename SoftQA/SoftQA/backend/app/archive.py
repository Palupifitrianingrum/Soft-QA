"""Upload validation and hardened ZIP extraction. Pure stdlib so it is easy to unit test.

Uploaded code is NEVER executed here; files are only written to disk as inert data.
"""
from __future__ import annotations

import io
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class UploadError(ValueError):
    """Raised for any rejected upload. Message is safe to show to the user."""


@dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 10 * 1024 * 1024
    max_entries: int = 2000
    max_files: int = 500
    max_file_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 50 * 1024 * 1024
    max_ratio: int = 100  # compressed -> uncompressed, zip-bomb guard


LANG_BY_EXT = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript"}
TEXT_EXTS = set(LANG_BY_EXT) | {".json", ".md", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".html", ".css", ".sql"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".mypy_cache", ".pytest_cache", "dist", "build"}


@dataclass
class ExtractedFile:
    path: str
    language: str
    size_bytes: int
    line_count: int


@dataclass
class ExtractionResult:
    files: list[ExtractedFile]
    skipped: int


def language_for(path: str) -> str:
    return LANG_BY_EXT.get(PurePosixPath(path).suffix.lower(), "text")


def detect_kind(filename: str, data: bytes, limits: Limits = Limits()) -> str:
    if len(data) > limits.max_upload_bytes:
        raise UploadError(f"File exceeds the {limits.max_upload_bytes // (1024 * 1024)} MB upload limit.")
    if not data:
        raise UploadError("Uploaded file is empty.")
    ext = Path(filename).suffix.lower()
    if ext == ".py":
        return "file"
    if ext == ".zip":
        return "zip"
    raise UploadError("Unsupported file type. Upload a .py file or a .zip source archive.")


def _decode(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def sanitize_member_path(name: str) -> PurePosixPath:
    """Normalise a zip member name; reject absolute paths, drive letters, NULs and '..' segments."""
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
        raise UploadError(f"Unsafe path in archive: {name!r}")
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UploadError(f"Path traversal detected in archive: {name!r}")
    return PurePosixPath(*parts)


def save_single_file(filename: str, data: bytes, dest: Path, limits: Limits = Limits()) -> ExtractionResult:
    text = _decode(data)
    if text is None:
        raise UploadError("File is not valid UTF-8 text.")
    if len(data) > limits.max_file_bytes:
        raise UploadError("Source file is too large.")
    safe = re.sub(r"[^\w.\-]", "_", Path(filename).name) or "upload.py"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / safe).write_text(text, encoding="utf-8")
    return ExtractionResult([ExtractedFile(safe, language_for(safe), len(data), len(text.splitlines()))], 0)


def extract_zip(data: bytes, dest: Path, limits: Limits = Limits()) -> ExtractionResult:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise UploadError("Not a valid ZIP archive.")
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise UploadError("Archive contains too many entries.")
        # Pass 1: validate every entry before writing anything.
        candidates: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        skipped = 0
        total = 0
        for info in infos:
            rel = sanitize_member_path(info.filename)
            if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise UploadError(f"Symlinks are not allowed in archives: {info.filename!r}")
            if info.flag_bits & 0x1:
                raise UploadError("Encrypted archives are not supported.")
            if info.is_dir() or not rel.parts:
                continue
            total += info.file_size
            if total > limits.max_total_bytes:
                raise UploadError("Archive expands beyond the allowed total size.")
            if info.compress_size and info.file_size > 1024 * 1024 and info.file_size / info.compress_size > limits.max_ratio:
                raise UploadError("Suspicious compression ratio (possible zip bomb).")
            if any(p in SKIP_DIRS for p in rel.parts[:-1]) or rel.suffix.lower() not in TEXT_EXTS or info.file_size > limits.max_file_bytes:
                skipped += 1
                continue
            candidates.append((info, rel))
        if len(candidates) > limits.max_files:
            raise UploadError(f"Archive has more than {limits.max_files} supported files.")
        # Strip a single shared top-level folder so module paths look natural.
        strip = 0
        if candidates and all(len(r.parts) > 1 for _, r in candidates) and len({r.parts[0] for _, r in candidates}) == 1:
            strip = 1
        out: dict[str, ExtractedFile] = {}
        for info, rel in candidates:
            rel = PurePosixPath(*rel.parts[strip:])
            with zf.open(info) as src:
                raw = src.read(limits.max_file_bytes + 1)  # headers can lie: bound the real read
            if len(raw) > limits.max_file_bytes:
                raise UploadError(f"File {rel} exceeds the per-file limit.")
            text = _decode(raw)
            if text is None:
                skipped += 1
                continue
            target = (dest_root / Path(*rel.parts)).resolve()
            if dest_root not in target.parents:
                raise UploadError(f"Path traversal detected: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            out[str(rel)] = ExtractedFile(str(rel), language_for(str(rel)), len(raw), len(text.splitlines()))
    if not out:
        raise UploadError("Archive contains no supported source files.")
    return ExtractionResult(sorted(out.values(), key=lambda f: f.path), skipped)
