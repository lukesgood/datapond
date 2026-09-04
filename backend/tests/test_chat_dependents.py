"""What a destructive change will break, and what could not be checked.

"Are you sure?" is not a confirmation. An empty list reads as "nothing depends on
this" — so a list that could not be computed must not be empty, it must say so.
"""
import pytest

from app.chat.dependents import Dependents


def test_it_carries_items_and_gaps():
    d = Dependents("policy rls-7 on crm.customers")
    d.item("table", "crm.customers", "loses row filtering entirely")
    d.skipped("PII detection not checked: no query engine on this deployment")
    assert d.done() == {
        "subject": "policy rls-7 on crm.customers",
        "items": [{"kind": "table", "name": "crm.customers",
                   "effect": "loses row filtering entirely"}],
        "not_checked": ["PII detection not checked: no query engine on this deployment"],
    }


def test_an_untouched_list_still_has_every_key():
    assert Dependents("x").done() == {"subject": "x", "items": [], "not_checked": []}


def test_nothing_found_and_nothing_checked_are_different_states():
    """The distinction the card renders differently, and the reason this type exists."""
    found_nothing = Dependents("x").done()
    could_not_check = Dependents("x").skipped("catalog unavailable").done()
    assert found_nothing["items"] == could_not_check["items"] == []
    assert not found_nothing["not_checked"]
    assert could_not_check["not_checked"]


def test_items_keep_the_order_they_were_added():
    d = Dependents("x")
    d.item("role", "viewer", "gains access")
    d.item("role", "analyst", "gains access")
    assert [i["name"] for i in d.done()["items"]] == ["viewer", "analyst"]


def test_kind_and_name_are_required_to_be_non_empty():
    """A blank row in a blast-radius list is worse than no row."""
    with pytest.raises(ValueError):
        Dependents("x").item("", "crm.customers", "effect")
    with pytest.raises(ValueError):
        Dependents("x").item("table", "", "effect")
