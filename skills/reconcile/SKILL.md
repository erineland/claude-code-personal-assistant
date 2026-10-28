---
name: reconcile
description: Reconcile a bank account against a budgeting app transaction by transaction. Finds missing transactions, phantom scheduled entries, amount mismatches and where a balance gap began, then proposes fixes for the user to approve one by one. Use when the user asks to reconcile their budget or check it matches the bank.
---

# Reconcile: bank ↔ budget

Someone who has logged every transaction for years does not want a "balance adjustment". They want
the ledger to be **true**. So this skill fixes real transactions, not totals, and every write is
approved individually (a `PreToolUse` hook forces a prompt on every mutating budget-app call).

## 🚀 Fast path
1. **Sync first.** Budget-app integrations often serve transactions from a local cache that can be
   hours stale while balances are live. Analysis on a stale cache produces confident, wrong
   "missing" items.
2. **Cheap pre-check:** has the bank export's modified time or the account balance changed since the
   last reconcile? If neither moved, the answer is the same as last time. Say so and stop.
3. `lib/match.py --gaps bank.csv ledger.csv`: find the **last day the running gap was 0**. Start there.
4. `lib/match.py bank.csv ledger.csv --since <that day>`: the real missing and extra rows.
5. Propose fixes, get a yes per transaction, write, then **re-run both** to verify.

## Ground truth
If the bank export has no balance column, the true balance is **the sum of every row since the
account opened**. That's also why a month-scoped run can't give a ground-truth balance: you need
the opening position too.

## Matching method (`lib/match.py`)
Integer pence · drop zero-value rows (card checks) · match by amount with a **widening date tolerance**
(exact date first, then ±1, ±2 …) · **self-check**: unmatched ledger − unmatched bank must equal the
gap, or the matcher is wrong and nothing gets reported. Payee names differ between systems: match on
amount + date, use names as hints.

## Known failure patterns
- **Offsetting errors hide in a matching balance.** A tiny net gap can sit on top of a missing income
  and an equal pile of missing charges. Never conclude "close enough" from the total.
- **Phantom recurring entries.** Scheduled transactions in the budget app fire whether or not the
  bank charged. They then steal the real import of the same amount, and the matcher blames an innocent
  row downstream. Trace the whole pool at that amount together.
- **Projections aren't transactions.** Some integrations list *upcoming* scheduled instances alongside
  real ones. Never call a projection a duplicate; check the full-history export.
- **Refund imported without its charge.** Add the charge in the refund's category so they cancel.
- **Manual adds race the bank import.** Don't hand-add anything from the last ~3 days; sync and
  re-check first, or you'll create duplicates.
- **The user tidying up mid-session.** Snapshot transaction IDs at the start. If the gap moves
  unexpectedly, diff them. Ask the user to pause manual edits while a reconcile runs.
- **Coverage before cause.** Before naming a root cause, check the data actually covers that period.
  An integration that returns only the last year will make an older gap look like something it isn't.
  Call it a hypothesis until full history confirms it.
- **"Success" that did nothing.** At least one API delete returned success, logged an undo entry, and
  left the record in place. **Re-read after every write.**

## Report, then fix with permission
Balances · gap-by-day table · missing-from-ledger · extra-in-ledger · numbered fix list. Give a
**scoped choice** (full fix: records become true; recent only: balance matches now, older errors
remain) and say what each leaves broken. Before creating a transaction, copy the payee's existing
category rather than inventing one. Memo every fix (`Recon YYYY-MM-DD: …`) so it's findable later.
Never lock (reconcile) records: that's the user's step in the app.

## Monthly unattended check
A scheduled headless run on the 3rd: **read-only** (all budget writes denied in its settings file),
writes one report file, and notifies only if a gap has **persisted for 3 days**. Gaps that move are
timing, not errors.
