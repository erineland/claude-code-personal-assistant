import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "reconcile", "lib"))
import match  # noqa: E402

D = datetime.date


def row(i, day, amount, payee=""):
    return {"id": i, "date": D(2030, 1, day), "amount": amount, "payee": payee}


class MatchTests(unittest.TestCase):
    def test_widening_tolerance_avoids_the_greedy_cascade(self):
        # A phantom recurring entry on the 3rd, real charges on the 5th and the 20th.
        # A single ±7-day pass pairs the phantom with the 5th, then can't place the ledger's
        # real 5th entry, and blames it. Exact-date-first pairs the 5th correctly.
        bank = [row("b1", 5, -999), row("b2", 20, -999)]
        ledger = [row("l1", 3, -999, "phantom"), row("l2", 5, -999), row("l3", 20, -999)]
        _, ub, ul = match.match(bank, ledger)
        self.assertEqual(ub, [])
        self.assertEqual([r["id"] for r in ul], ["l1"])

    def test_self_check_holds(self):
        bank = [row("b1", 1, -500), row("b2", 2, 100000)]
        ledger = [row("l1", 1, -500), row("l2", 9, -1299)]
        _, ub, ul = match.match(bank, ledger)
        gap, explained, ok = match.self_check(bank, ledger, ub, ul)
        self.assertTrue(ok)
        self.assertEqual(gap, explained)

    def test_offsetting_errors_are_still_listed(self):
        # Net gap is zero, but there's a missing income and an equal missing charge.
        bank = [row("b1", 2, 100000), row("b2", 4, -100000)]
        ledger = []
        _, ub, ul = match.match(bank, ledger)
        gap, _, ok = match.self_check(bank, ledger, ub, ul)
        self.assertEqual(gap, 0)
        self.assertTrue(ok)
        self.assertEqual(len(ub), 2)

    def test_running_gap_finds_where_it_started(self):
        bank = [row("b1", 1, -100), row("b2", 3, -250)]
        ledger = [row("l1", 1, -100)]
        series = dict(match.running_gap(bank, ledger))
        self.assertEqual(series[D(2030, 1, 1)], 0)
        self.assertEqual(series[D(2030, 1, 3)], 250)

    def test_pence_is_exact(self):
        self.assertEqual(match.pence("-0.10") + match.pence("-0.20"), match.pence("-0.30"))


if __name__ == "__main__":
    unittest.main()
