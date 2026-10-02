# -*- coding: utf-8 -*-
"""Canonical identity for a stocked item.

This module exists because of one real, expensive class of bug: the same
physical product written two slightly different ways becomes two separate
stock records. Branch A then "has" 3 units under one spelling and 0 under
the other, transfers get rejected for insufficient stock while the shelf
is visibly full, and the ledger can never be reconciled because it is
tracking a product that does not exist.

The worst offender in practice is a signed decimal that can be written
two ways and LOOKS identical to a human on screen: "-0.00" and "0.00".
They are different strings, so a dictionary keyed on the raw text treats
them as different products - while every person looking at the screen
reads them as the same thing.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def normalize_measure(value: str | float | int | Decimal, places: int = 2) -> str:
    """Canonicalize a signed decimal measurement to one unambiguous form.

    Collapses negative zero, pads to a fixed number of decimal places, and
    drops a redundant leading '+'. "-0.00", "0", "+0.000" and 0.0 all come
    back as the same string.
    """
    try:
        number = Decimal(str(value).strip().lstrip("+"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a usable measurement: {value!r}") from exc

    quantized = number.quantize(Decimal(1).scaleb(-places))

    if quantized == 0:
        quantized = abs(quantized)  # kill negative zero, the actual bug

    return f"{quantized:.{places}f}"


def item_key(product: str, sphere: str | float, cylinder: str | float) -> str:
    """Build the key everything else - stock counts, transfers, the
    ledger - is stored against.

    Every entry point into the system must build keys through here. A
    single caller that formats its own key reintroduces exactly the split
    this module exists to prevent, and it will not be noticed until the
    stock numbers stop adding up.
    """
    cleaned_product = " ".join(product.strip().upper().split())
    if not cleaned_product:
        raise ValueError("product must not be blank")
    return f"{cleaned_product}|{normalize_measure(sphere)}|{normalize_measure(cylinder)}"
