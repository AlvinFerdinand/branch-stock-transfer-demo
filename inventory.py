# -*- coding: utf-8 -*-
"""Branch stock with an explicit send/receive handshake.

The core decision: **stock leaves the sending branch the moment it is
shipped, and does not arrive at the destination until someone there
confirms receipt.** In between it belongs to neither branch - it is in
transit, and it is visible as such.

The tempting simplification is to move the quantity from one branch to
the other in a single step at send time. It is wrong in a way that only
shows up in the real world: goods spend days in transit, and during those
days the destination's stock figure claims items that are physically in a
courier's van. Staff order against stock they cannot sell, and nobody can
tell a delayed shipment from a lost one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ledger import Movement, StockLedger


class ShipmentStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"


@dataclass
class Shipment:
    id: str
    source: str
    destination: str
    item: str
    qty: int
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT


class InsufficientStockError(Exception):
    def __init__(self, branch: str, item: str, available: int, requested: int):
        super().__init__(
            f"{branch} has {available} of {item}, cannot send {requested}"
        )
        self.branch, self.item = branch, item
        self.available, self.requested = available, requested


class ShipmentStateError(Exception):
    """Raised when an operation doesn't make sense for a shipment's
    current state - receiving something already received, cancelling
    something already delivered."""


class InventoryService:
    def __init__(self, ledger: StockLedger | None = None):
        self._stock: dict[tuple[str, str], int] = {}
        self._shipments: dict[str, Shipment] = {}
        self._ledger = ledger or StockLedger()
        self.ledger_failures: int = 0

    # ---- stock ---------------------------------------------------------

    def quantity(self, branch: str, item: str) -> int:
        return self._stock.get((branch, item), 0)

    def in_transit(self, item: str | None = None) -> int:
        return sum(
            s.qty for s in self._shipments.values()
            if s.status is ShipmentStatus.IN_TRANSIT and (item is None or s.item == item)
        )

    def _apply(self, branch: str, item: str, change: int, reason: str, ref: str = "") -> None:
        """Change stock, then record it. Order matters - see ledger.py."""
        new_balance = self.quantity(branch, item) + change
        self._stock[(branch, item)] = new_balance

        try:
            self._ledger.record(Movement(
                branch=branch, item=item, change=change,
                balance_after=new_balance, reason=reason, ref=ref,
            ))
        except Exception:
            # Deliberately swallowed: the goods have already physically
            # moved. Counting the failure keeps it visible instead of
            # silent.
            self.ledger_failures += 1

    def stock_in(self, branch: str, item: str, qty: int, reason: str = "stocktake", ref: str = "") -> None:
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._apply(branch, item, qty, reason, ref)

    def sell(self, branch: str, item: str, qty: int, ref: str = "") -> None:
        available = self.quantity(branch, item)
        if qty > available:
            raise InsufficientStockError(branch, item, available, qty)
        self._apply(branch, item, -qty, "sale", ref)

    # ---- transfers ------------------------------------------------------

    def send(self, shipment_id: str, source: str, destination: str,
             item: str, qty: int) -> Shipment:
        if shipment_id in self._shipments:
            raise ShipmentStateError(f"shipment {shipment_id} already exists")
        if source == destination:
            raise ValueError("source and destination must differ")
        if qty <= 0:
            raise ValueError("qty must be positive")

        available = self.quantity(source, item)
        if qty > available:
            raise InsufficientStockError(source, item, available, qty)

        self._apply(source, item, -qty, "send", shipment_id)
        shipment = Shipment(shipment_id, source, destination, item, qty)
        self._shipments[shipment_id] = shipment
        return shipment

    def receive(self, shipment_id: str) -> Shipment:
        shipment = self._require(shipment_id)
        if shipment.status is not ShipmentStatus.IN_TRANSIT:
            # The single most important guard in this file. Receiving
            # twice - a double-tapped button, a retried request - would
            # create stock out of nothing.
            raise ShipmentStateError(
                f"shipment {shipment_id} is {shipment.status.value}, cannot receive it again"
            )

        self._apply(shipment.destination, shipment.item, shipment.qty, "receive", shipment_id)
        shipment.status = ShipmentStatus.RECEIVED
        return shipment

    def cancel(self, shipment_id: str) -> Shipment:
        """Recall a shipment that never arrived: the stock goes back to
        the branch it left."""
        shipment = self._require(shipment_id)
        if shipment.status is not ShipmentStatus.IN_TRANSIT:
            raise ShipmentStateError(
                f"shipment {shipment_id} is {shipment.status.value}, cannot cancel it"
            )

        self._apply(shipment.source, shipment.item, shipment.qty, "cancel", shipment_id)
        shipment.status = ShipmentStatus.CANCELLED
        return shipment

    def _require(self, shipment_id: str) -> Shipment:
        if shipment_id not in self._shipments:
            raise ShipmentStateError(f"no such shipment: {shipment_id}")
        return self._shipments[shipment_id]

    # ---- reconciliation --------------------------------------------------

    def reconcile(self, branch: str, item: str) -> bool:
        """Does the live stock figure match what the ledger says happened?"""
        return self.quantity(branch, item) == self._ledger.replay_balance(branch, item)
