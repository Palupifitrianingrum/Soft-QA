import io, stat, tempfile, unittest, zipfile
from pathlib import Path

from app.archive import Limits, UploadError, detect_kind, extract_zip, sanitize_member_path


def make_zip(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_rejects_traversal(self):
        for bad in ["../evil.py", "a/../../evil.py", "/abs.py", "C:/x.py", "..\\evil.py"]:
            with self.assertRaises(UploadError):
                sanitize_member_path(bad)

    def test_zip_with_traversal_rejected_and_nothing_written(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(UploadError):
                extract_zip(make_zip({"ok.py": "x=1", "../evil.py": "x=2"}), Path(d) / "src")
            self.assertFalse(list(Path(d).rglob("*.py")))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(UploadError):
                extract_zip(make_zip({"a.py": "x=1"}, symlink="link.py"), Path(d))

    def test_valid_zip_strips_root_and_skips_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            res = extract_zip(make_zip({"proj/a.py": "x=1\ny=2\n", "proj/b.exe": "MZ", "proj/.git/c.py": "z"}), Path(d))
            self.assertEqual([f.path for f in res.files], ["a.py"])
            self.assertEqual(res.files[0].line_count, 2)
            self.assertEqual(res.skipped, 2)

    def test_too_many_files_and_bomb_limits(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(UploadError):
                extract_zip(make_zip({f"f{i}.py": "x=1" for i in range(5)}), Path(d), Limits(max_files=3))
            with self.assertRaises(UploadError):
                extract_zip(make_zip({"big.py": "a" * 5000}), Path(d), Limits(max_total_bytes=1000))

    def test_not_a_zip_and_bad_types(self):
        with self.assertRaises(UploadError):
            extract_zip(b"not a zip", Path(tempfile.gettempdir()) / "x")
        with self.assertRaises(UploadError):
            detect_kind("evil.exe", b"MZ")
        with self.assertRaises(UploadError):
            detect_kind("a.py", b"x" * 20, Limits(max_upload_bytes=10))
        self.assertEqual(detect_kind("a.PY", b"x=1"), "file")


if __name__ == "__main__":
    unittest.main()
