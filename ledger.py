# -*- coding: utf-8 -*-
"""An append-only record of every stock movement.

Two design rules here, both learned the hard way in the system this
mirrors:

1. **The ledger entry is written AFTER the stock actually changes**, and
   records the resulting balance. Writing it before means recording a
   number that may never come true if the operation fails later - and a
   ledger that disagrees with the stock table is worse than no ledger,
   because people trust it.

2. **A failing ledger must never fail the business operation.** A branch
   must still be able to sell, ship and receive goods when the audit
   writer is broken. Recording is important; blocking the shop floor
   because recording broke is not. Failures are counted and surfaced
   rather than swallowed silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class Movement:
    branch: str
    item: str
    change: int           # signed: -2 means two units left this branch
    balance_after: int
    reason: str           # "sale", "send", "receive", "cancel", "stocktake", ...
    ref: str = ""         # the document this came from
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StockLedger:
    """The default, in-memory implementation. A real one writes rows."""

    def __init__(self) -> None:
        self._movements: list[Movement] = []

    def record(self, movement: Movement) -> None:
        self._movements.append(movement)

    # ---- reading back -------------------------------------------------

    @property
    def movements(self) -> list[Movement]:
        return list(self._movements)

    def for_branch(self, branch: str) -> list[Movement]:
        return [m for m in self._movements if m.branch == branch]

    def replay_balance(self, branch: str, item: str) -> int:
        """Rebuild a branch's quantity from the movement history alone.

        This is the point of keeping the ledger: if the stock table and
        the replayed history ever disagree, something wrote stock without
        recording it, and you can find out WHEN rather than guessing.
        """
        return sum(
            m.change for m in self._movements if m.branch == branch and m.item == item
        )
