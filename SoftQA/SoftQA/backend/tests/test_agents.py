import unittest

from app.agents.bug_hunter import hunt
from app.agents.evaluator import merge_findings, quality_score
from app.findings import RawFinding

SRC = "def avg(xs, n=[]):\n    return sum(xs) / len(xs)\n\ndef g(a, b):\n    try:\n        return a / b\n    except:\n        pass\n    if a == None:\n        return 0\n"


def rf(source, cat, s, e, sev="medium", status="potential", title="t"):
    return RawFinding(source, title, sev, cat, "a.py", s, e, "d", "ev", "r", 0.5, status)


class AgentTests(unittest.TestCase):
    def test_bug_hunter_patterns(self):
        rules = {f.rule_id for f in hunt("a.py", SRC)}
        self.assertTrue({"aura.division-by-variable", "aura.mutable-default", "aura.broad-except", "aura.eq-none"} <= rules)
        for f in hunt("a.py", SRC):
            self.assertLessEqual(f.line_end, len(SRC.splitlines()))
            self.assertEqual(f.status, "potential")

    def test_syntax_error_is_confirmed(self):
        f = hunt("a.py", "def x(:\n")[0]
        self.assertEqual((f.status, f.rule_id), ("confirmed", "aura.syntax-error"))

    def test_merge_corroborates_ai_with_tool(self):
        tool = rf("ruff", "runtime", 10, 10, "high", "confirmed")
        ai = rf("ai", "runtime", 10, 11)
        other = rf("ai", "performance", 40, 41)
        out = merge_findings([ai, tool, other])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].corroborated_by, ["ai"])
        self.assertEqual(out[0].status, "confirmed")

    def test_score_is_bounded_and_weights_potential_half(self):
        self.assertEqual(quality_score([]), 100)
        self.assertEqual(quality_score([rf("ruff", "runtime", 1, 1, "high", "confirmed")]), 92)
        self.assertEqual(quality_score([rf("ai", "logic", 1, 1, "high", "potential")]), 96)
        self.assertEqual(quality_score([rf("ruff", "runtime", 1, 1, "critical", "confirmed")] * 20), 0)


if __name__ == "__main__":
    unittest.main()
