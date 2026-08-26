"""Listing collections at scale.

The list had no LIMIT and aggregated ai_chunks for every collection on every page
load, the frontend rendered all of them into a column with no scroll bound, and there
was no way to search. None of that shows on a deployment with one collection, which
is the only kind anyone had tried.

The paging contract is the part worth pinning: other callers — the assistant's
executors, the API page — use this endpoint to enumerate, so a default limit would
silently truncate them. Paging happens when asked for and not otherwise.
"""
import pytest

from app.api.ai_vectors import listing_window


def test_no_paging_asked_for_means_everything():
    """The assistant enumerates collections through this endpoint. A default limit
    would make it quietly forget the ones past the cutoff."""
    assert listing_window(None, None) == (None, 0)


def test_a_limit_is_honoured():
    assert listing_window(50, None) == (50, 0)


def test_an_offset_without_a_limit_still_pages():
    assert listing_window(None, 100) == (None, 100)


def test_a_limit_is_capped_so_one_request_cannot_ask_for_everything():
    assert listing_window(100_000, 0)[0] == 500


def test_nonsense_paging_is_clamped_rather_than_erroring():
    assert listing_window(-5, -20) == (1, 0)
