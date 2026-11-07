import unittest

from app.validation import check_range, evidence_matches, validate_test_code

GOOD = "import pytest\nfrom calc import div\n\ndef test_div_zero():\n    with pytest.raises(ZeroDivisionError):\n        div(1, 0)\n"


class ValidationTests(unittest.TestCase):
    def test_line_range(self):
        self.assertEqual(check_range(2, 4, 10), (2, 4))
        self.assertEqual(check_range(2, 99, 10), (2, 10))
        self.assertIsNone(check_range(0, 3, 10))
        self.assertIsNone(check_range(11, 12, 10))
        self.assertIsNone(check_range("x", 1, 10))

    def test_evidence(self):
        lines = ["def f(a, b):", "    return a / b", "x = 1"]
        self.assertTrue(evidence_matches("return a /   b", lines, 2, 2))
        self.assertFalse(evidence_matches("return a // b", lines, 2, 2))
        self.assertFalse(evidence_matches("", lines, 2, 2))

    def test_good_test_passes(self):
        problems, name = validate_test_code(GOOD, {"calc"})
        self.assertEqual(problems, [])
        self.assertEqual(name, "test_div_zero")

    def test_dangerous_code_rejected(self):
        bad = [
            "import os\ndef test_x():\n    assert os.system('id') == 0\n",
            "def test_x():\n    assert open('/etc/passwd')\n",
            "def test_x():\n    assert ().__class__\n",
            "import subprocess\ndef test_x():\n    assert True\n",
            "from calc import *\ndef test_x():\n    assert True\n",
            "print(1)\ndef test_x():\n    assert True\n",
            "def test_x():\n    pass\n",
            "def test_x(:\n",
            "def test_a():\n    assert 1\ndef test_b():\n    assert 1\n",
        ]
        for code in bad:
            problems, _ = validate_test_code(code, {"calc"})
            self.assertTrue(problems, code)


if __name__ == "__main__":
    unittest.main()
