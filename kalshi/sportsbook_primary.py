"""Sportsbook-primary fair value with statistical model as veto.

Highest-priority change for the Prop NO maker: when fresh sportsbook coverage
exists (exact line or nearby-line translation), use it as the primary fair
probability. The Poisson model is used only to veto when it disagrees strongly
in a direction that has historically correlated with adverse selection.

This module is intentionally side-effect free so it can be adopted in paper
mode or as a new forward-validation cohort before any live change.
"""

from __future__ import annotations

import pandas as pd


def primary_fair_value(
    frame: pd.DataFrame,
    *,
    book_col: str = "p_book",
    model_col: str = "p_model",
    min_books: int = 2,
    veto_threshold: float = 0.08,
) -> pd.DataFrame:
    """Return a copy with ``p_fair`` and ``fair_source`` columns.

    Parameters
    ----------
    frame
        Must contain the book and model probability columns.
    book_col, model_col
        Column names for sportsbook consensus (or translated) and model.
    min_books
        Minimum number of books required to trust the book price.
    veto_threshold
        Absolute probability gap above which the model vetoes the book price
        (model is used instead, or the row is marked for skipping).
    """
    out = frame.copy()
    has_book = (
        out[book_col].notna()
        & out.get("book_n", 0).ge(min_books)
        & out[book_col].between(0.02, 0.98)
    )
    gap = (out[model_col] - out[book_col]).abs()
    strong_disagree = has_book & gap.ge(veto_threshold)

    # Default to model; override with book when coverage is good and no veto.
    out["p_fair"] = out[model_col]
    out["fair_source"] = "model"
    use_book = has_book & ~strong_disagree
    out.loc[use_book, "p_fair"] = out.loc[use_book, book_col]
    out.loc[use_book, "fair_source"] = "book"
    out.loc[strong_disagree, "fair_source"] = "model_veto"
    return out


def should_quote_no(
    fair: pd.Series,
    no_price: pd.Series,
    *,
    min_edge: float = 0.0,
    max_edge: float = 0.15,
    fee_fn=None,
) -> pd.Series:
    """Boolean mask: quote resting NO when edge after fee is in the allowed band.

    ``fee_fn`` should accept a price and return the maker fee per contract.
    """
    if fee_fn is None:

        def fee_fn(p):
            return 0.25 * 0.07 * p * (1 - p)  # default maker share

    fee = fee_fn(no_price)
    edge = (1 - fair) - no_price - fee
    return (edge >= min_edge) & (edge <= max_edge)
