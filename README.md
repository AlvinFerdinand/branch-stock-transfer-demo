# branch-stock-transfer-demo

> **Demo reconstruction of a real production system.** The original is the
> point-of-sale and stock system I built for **Optik Rizki Eye Plus**
> (Indonesia), running across dozens of retail branches: sales, inter-branch
> stock transfers with scan-based receipt confirmation, and a stock movement
> trail. That system's code, its product catalogue, branch list and
> transaction data belong to the business and are **not** published here.
> This repository is a clean-room rebuild of three of its design decisions,
> on invented data, so they can be shown and tested in the open.

Inter-branch stock transfer with an explicit send/receive handshake, an
append-only movement ledger, and canonical item identity. Pure Python,
no dependencies beyond pytest.

---

## 1. Stock leaves on send, arrives on receipt — not both at once

The tempting simplification is to move the quantity from one branch to the
other in a single step when the shipment is created. It's wrong in a way
that only shows up in the real world: goods spend days in transit, and
during those days the destination's stock figure claims items that are
physically in a courier's van. Staff sell against stock they don't have,
and nobody can distinguish a delayed shipment from a lost one.

```python
inv.send("SHP-1", "BRANCH-A", "BRANCH-B", item, qty=4)
inv.quantity("BRANCH-A", item)   # 6 - gone from the sender
inv.quantity("BRANCH-B", item)   # 0 - not there yet
inv.in_transit(item)             # 4 - and visible as such

inv.receive("SHP-1")
inv.quantity("BRANCH-B", item)   # 4
```

Guarded, with a test each: **receiving twice is refused** (a double-tapped
confirm button must not create stock out of nothing), cancelling returns
the goods to the sender, cancelling after receipt is refused, and in-transit
stock can't be sold by either branch.

## 2. The ledger is written after the change, and never blocks the business

Two rules, both learned from the real system:

- **The movement is recorded after the stock actually changes**, storing
  the resulting balance. Recording first means writing a number that may
  never come true — and a ledger that disagrees with the stock table is
  worse than no ledger, because people trust it.
- **A failing ledger must never fail the operation.** A branch has to keep
  selling and receiving goods when the audit writer is down. Failures are
  counted and surfaced (`ledger_failures`), not swallowed silently.

`reconcile()` replays the ledger and compares it to the live quantity — if
they ever disagree, something changed stock without recording it, and you
can find out when instead of guessing.

## 3. One spelling per product, enforced at the boundary

The expensive bug this prevents: the same physical product written two
slightly different ways becomes two separate stock records. A branch "has
none" of an item sitting on its own shelf, transfers get rejected for
insufficient stock, and the ledger can never be reconciled.

The worst offender is a signed decimal with two spellings that look
**identical on screen**:

```python
item_key("LENS CLEAR", "-0.00", "0.00") == item_key("LENS CLEAR", "0.00", "-0.00")  # True
normalize_measure("-0.00")   # "0.00"  - negative zero collapsed
normalize_measure("+1.5")    # "1.50"  - padded, sign normalized
normalize_measure("n/a")     # ValueError - rejected loudly, never guessed
```

Product names are case- and whitespace-normalized for the same reason.

## Run the tests

```bash
pip install pytest
python -m pytest tests/ -v
```

21 tests covering the full shipment lifecycle and every refusal path, the
ledger's ordering and failure-tolerance guarantees, ledger-vs-stock
reconciliation, and item-key canonicalization.

## License

MIT.
