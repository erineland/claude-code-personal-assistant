#!/usr/bin/env python3
"""Match a bank export against a budgeting app's ledger, and prove the matching is sound.

Usage:
  python3 match.py bank.csv ledger.csv [--since YYYY-MM-DD] [--max-days 14]
  python3 match.py --gaps bank.csv ledger.csv          # day-by-day running gap

Both CSVs need `date` (YYYY-MM-DD), `amount` (signed, e.g. -12.99) and optionally `id` and `payee`.

Method (each rule exists because the naive version gave a wrong answer):
  1. Integer pence, never floats.
  2. Drop zero-value rows: banks log card checks as 0.00, and they drown the real findings.
  3. Match by amount with a WIDENING date tolerance: every exact-date pair first, then ±1 day,
     ±2 ... up to --max-days. A single greedy pass at ±7 days lets one phantom entry steal a real
     transaction and pushes the error onto an innocent one further along.
  4. Self-check: sum(unmatched ledger) - sum(unmatched bank) must equal the balance gap over the
     same window. If it doesn't, the matcher is wrong; don't report anything.
  5. A small net gap proves nothing. Two offsetting errors (a missing income and an equal pile of
     missing charges) look "reconciled". Always look at the unmatched lists, not just the total.
"""
import argparse
import csv
import datetime
import sys
from collections import defaultdict
from decimal import Decimal


def pence(s):
    return int((Decimal(str(s).replace(",", "")) * 100).to_integral_value())


def load(path, since=None):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            day = datetime.date.fromisoformat(r["date"].strip()[:10])
            amount = pence(r["amount"])
            if amount == 0 or (since and day < since):
                continue
            rows.append({"id": r.get("id") or f"{path}:{i}", "date": day, "amount": amount,
                         "payee": (r.get("payee") or "").strip()})
    return rows


def match(bank, ledger, max_days=14):
    """Pair rows of equal amount, nearest dates first. Returns (pairs, unmatched_bank, unmatched_ledger)."""
    free_bank = defaultdict(list)
    for b in bank:
        free_bank[b["amount"]].append(b)
    used_bank, used_ledger, pairs = set(), set(), []
    for tol in range(max_days + 1):
        for l in sorted(ledger, key=lambda r: r["date"]):
            if l["id"] in used_ledger:
                continue
            candidates = [b for b in free_bank[l["amount"]]
                          if b["id"] not in used_bank and abs((b["date"] - l["date"]).days) == tol]
            if candidates:
                b = min(candidates, key=lambda r: r["date"])
                used_bank.add(b["id"])
                used_ledger.add(l["id"])
                pairs.append((b, l, tol))
    unmatched_bank = [b for b in bank if b["id"] not in used_bank]
    unmatched_ledger = [l for l in ledger if l["id"] not in used_ledger]
    return pairs, unmatched_bank, unmatched_ledger


def self_check(bank, ledger, unmatched_bank, unmatched_ledger):
    gap = sum(r["amount"] for r in ledger) - sum(r["amount"] for r in bank)
    explained = sum(r["amount"] for r in unmatched_ledger) - sum(r["amount"] for r in unmatched_bank)
    return gap, explained, gap == explained


def running_gap(bank, ledger):
    """[(day, cumulative ledger - cumulative bank)]. The last day it sat at 0 is where to start looking."""
    delta = defaultdict(int)
    for r in ledger:
        delta[r["date"]] += r["amount"]
    for r in bank:
        delta[r["date"]] -= r["amount"]
    out, total = [], 0
    for day in sorted(delta):
        total += delta[day]
        out.append((day, total))
    return out


def fmt(p):
    sign = "-" if p < 0 else ""
    return f"{sign}{abs(p) // 100}.{abs(p) % 100:02d}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bank")
    ap.add_argument("ledger")
    ap.add_argument("--since", type=datetime.date.fromisoformat)
    ap.add_argument("--max-days", type=int, default=14)
    ap.add_argument("--gaps", action="store_true")
    a = ap.parse_args(argv)
    bank, ledger = load(a.bank, a.since), load(a.ledger, a.since)

    if a.gaps:
        last_zero = None
        for day, gap in running_gap(bank, ledger):
            last_zero = day if gap == 0 else last_zero
            print(f"{day}  {fmt(gap):>10}")
        print(f"\nLast day the gap was 0: {last_zero or 'never in this window'}")
        return 0

    pairs, ub, ul = match(bank, ledger, a.max_days)
    gap, explained, ok = self_check(bank, ledger, ub, ul)
    print(f"matched {len(pairs)} · bank-only {len(ub)} · ledger-only {len(ul)} · gap {fmt(gap)}")
    if not ok:
        print(f"SELF-CHECK FAILED: unmatched rows explain {fmt(explained)}, gap is {fmt(gap)}. "
              "Don't trust these lists.", file=sys.stderr)
        return 2
    for title, rows in (("Missing from the ledger (in the bank only)", ub),
                        ("Extra in the ledger (no bank row)", ul)):
        if rows:
            print(f"\n{title}:")
            for r in sorted(rows, key=lambda r: r["date"]):
                print(f"  {r['date']}  {fmt(r['amount']):>10}  {r['payee']}")
    far = [p for p in pairs if p[2] >= 5]
    if far:
        print("\nPaired 5+ days apart (check for a duplicate or a phantom recurring entry):")
        for b, l, tol in far:
            print(f"  {fmt(b['amount']):>10}  bank {b['date']} ↔ ledger {l['date']} ({tol}d)  {l['payee']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
