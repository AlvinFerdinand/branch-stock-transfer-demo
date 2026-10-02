# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from inventory import (InsufficientStockError, InventoryService, ShipmentStateError,
                       ShipmentStatus)
from item_key import item_key, normalize_measure
from ledger import StockLedger

ITEM = item_key("LENS CLEAR 1.56", sphere="-2.25", cylinder="-0.75")


def seeded(branch="BRANCH-A", qty=10) -> InventoryService:
    inv = InventoryService()
    inv.stock_in(branch, ITEM, qty)
    return inv


# ---- the send/receive handshake -------------------------------------------

def test_stock_leaves_the_sender_immediately_and_is_not_at_the_destination_yet():
    inv = seeded()
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 4)

    assert inv.quantity("BRANCH-A", ITEM) == 6   # gone from the sender
    assert inv.quantity("BRANCH-B", ITEM) == 0   # not yet arrived
    assert inv.in_transit(ITEM) == 4             # and visible as in transit


def test_receiving_puts_the_stock_at_the_destination():
    inv = seeded()
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 4)
    shipment = inv.receive("SHP-1")

    assert shipment.status is ShipmentStatus.RECEIVED
    assert inv.quantity("BRANCH-B", ITEM) == 4
    assert inv.in_transit(ITEM) == 0


def test_receiving_twice_is_refused_and_creates_no_stock():
    # A double-tapped confirm button or a retried request must not
    # conjure units out of nothing.
    inv = seeded()
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 4)
    inv.receive("SHP-1")

    with pytest.raises(ShipmentStateError):
        inv.receive("SHP-1")

    assert inv.quantity("BRANCH-B", ITEM) == 4   # still 4, not 8


def test_cancelling_returns_the_stock_to_the_sender():
    inv = seeded()
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 4)
    inv.cancel("SHP-1")

    assert inv.quantity("BRANCH-A", ITEM) == 10
    assert inv.quantity("BRANCH-B", ITEM) == 0
    assert inv.in_transit(ITEM) == 0


def test_cancelling_after_receipt_is_refused():
    inv = seeded()
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 4)
    inv.receive("SHP-1")

    with pytest.raises(ShipmentStateError):
        inv.cancel("SHP-1")

    assert inv.quantity("BRANCH-A", ITEM) == 6   # unchanged by the failed cancel


def test_cannot_send_more_than_the_branch_actually_has():
    inv = seeded(qty=3)
    with pytest.raises(InsufficientStockError):
        inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 5)
    assert inv.quantity("BRANCH-A", ITEM) == 3   # nothing was deducted


def test_in_transit_stock_cannot_be_sold_by_either_branch():
    inv = seeded(qty=5)
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 5)

    with pytest.raises(InsufficientStockError):
        inv.sell("BRANCH-A", ITEM, 1)     # sender no longer has it
    with pytest.raises(InsufficientStockError):
        inv.sell("BRANCH-B", ITEM, 1)     # receiver does not have it yet


def test_duplicate_shipment_id_is_refused():
    inv = seeded()
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 2)
    with pytest.raises(ShipmentStateError):
        inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 2)


# ---- the ledger -------------------------------------------------------------

def test_every_movement_is_recorded_with_the_balance_that_resulted():
    inv = seeded(qty=10)
    inv.sell("BRANCH-A", ITEM, 2, ref="INV-77")
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 3)
    inv.receive("SHP-1")

    reasons = [(m.branch, m.reason, m.change, m.balance_after)
               for m in inv._ledger.movements]
    assert reasons == [
        ("BRANCH-A", "stocktake", 10, 10),
        ("BRANCH-A", "sale", -2, 8),
        ("BRANCH-A", "send", -3, 5),
        ("BRANCH-B", "receive", 3, 3),
    ]


def test_ledger_replay_reproduces_the_live_quantity():
    inv = seeded(qty=10)
    inv.sell("BRANCH-A", ITEM, 2)
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 3)
    inv.receive("SHP-1")

    assert inv.reconcile("BRANCH-A", ITEM)
    assert inv.reconcile("BRANCH-B", ITEM)


def test_a_broken_ledger_does_not_stop_goods_from_moving():
    # The shop floor keeps working when the audit writer breaks - but the
    # failure is counted, not silently dropped.
    class BrokenLedger(StockLedger):
        def record(self, movement):
            raise RuntimeError("audit database unreachable")

    inv = InventoryService(ledger=BrokenLedger())
    inv.stock_in("BRANCH-A", ITEM, 5)
    inv.send("SHP-1", "BRANCH-A", "BRANCH-B", ITEM, 2)
    inv.receive("SHP-1")

    assert inv.quantity("BRANCH-A", ITEM) == 3
    assert inv.quantity("BRANCH-B", ITEM) == 2
    assert inv.ledger_failures == 3


# ---- item identity ----------------------------------------------------------

def test_negative_zero_and_plain_zero_are_the_same_product():
    # The real bug this guards against: two spellings that render
    # identically on screen becoming two separate stock records, so a
    # branch "has none" of an item sitting on its own shelf.
    assert item_key("LENS CLEAR", "-0.00", "0.00") == item_key("LENS CLEAR", "0.00", "-0.00")


def test_stock_is_not_split_across_two_spellings_of_the_same_item():
    inv = InventoryService()
    inv.stock_in("BRANCH-A", item_key("LENS CLEAR", "-0.00", "0.00"), 5)

    # Looked up the other way round - must find the same 5 units.
    assert inv.quantity("BRANCH-A", item_key("LENS CLEAR", "0.00", "-0.00")) == 5
    inv.sell("BRANCH-A", item_key("LENS CLEAR", "0", "0"), 5)
    assert inv.quantity("BRANCH-A", item_key("LENS CLEAR", "-0.00", "-0.00")) == 0


@pytest.mark.parametrize("written,canonical", [
    ("-0.00", "0.00"),
    ("+0.000", "0.00"),
    (0.0, "0.00"),
    ("1.5", "1.50"),
    ("+1.50", "1.50"),
    ("-2.25", "-2.25"),
])
def test_measurements_canonicalize_to_one_form(written, canonical):
    assert normalize_measure(written) == canonical


def test_product_name_spacing_and_case_do_not_split_stock():
    assert item_key("lens  clear 1.56", "-1.00", "0") == item_key("LENS CLEAR 1.56", "-1.00", "0.00")


def test_blank_or_unparseable_values_are_rejected_loudly():
    with pytest.raises(ValueError):
        item_key("", "0", "0")
    with pytest.raises(ValueError):
        normalize_measure("n/a")
