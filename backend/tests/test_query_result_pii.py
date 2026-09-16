"""The rows a query returns go through the PII guardrail.

Ingest, retrieval, citations and the AI SQL prompt were all masked; `/queries/execute`
handed its cells straight to the caller, so `SELECT * FROM customers` returned every
RRN and card number the table held (POSITIONING_FIT_AUDIT §2.4).
"""
import pytest

from app.api.queries import mask_result_rows

RRN = "901231-1234567"          # valid check digit — see app/guardrails/pii_ko
ROWS = [["alice", RRN, 42], ["bob", "no pii here", 7]]


@pytest.fixture
def mode(monkeypatch):
    def _set(value):
        monkeypatch.setenv("PII_GUARDRAIL_MODE", value)
    return _set


def test_mask_mode_replaces_the_value_and_counts_it(mode):
    mode("mask")
    rows, count, blocked = mask_result_rows(ROWS, ["name", "id", "n"])
    assert blocked is False and count == 1
    assert RRN not in str(rows)
    assert rows[0][0] == "alice" and rows[0][2] == 42       # untouched cells survive
    assert rows[1] == ["bob", "no pii here", 7]


def test_block_mode_reports_it_and_does_not_hand_back_masked_rows(mode):
    """Blocked means the caller gets a refusal; returning masked rows instead would
    quietly turn block into mask."""
    mode("block")
    rows, count, blocked = mask_result_rows(ROWS, ["name", "id", "n"])
    assert blocked is True and count == 1
    assert rows is ROWS


def test_off_mode_does_not_scan(mode, monkeypatch):
    mode("off")
    from app.guardrails import pii_ko

    def _boom(*a, **k):
        raise AssertionError("detect() ran with the guardrail off")

    monkeypatch.setattr(pii_ko, "detect", _boom)
    rows, count, blocked = mask_result_rows(ROWS, ["name", "id", "n"])
    assert rows is ROWS and count == 0 and blocked is False


def test_non_string_cells_and_empty_results_are_left_alone(mode):
    mode("mask")
    assert mask_result_rows([], []) == ([], 0, False)
    rows, count, _ = mask_result_rows([[None, 3, 4.5, True]], ["a", "b", "c", "d"])
    assert rows == [[None, 3, 4.5, True]] and count == 0


def test_every_value_in_a_cell_is_counted(mode):
    mode("mask")
    _rows, count, _ = mask_result_rows([[f"{RRN} and {RRN}"]], ["c"])
    assert count == 2
