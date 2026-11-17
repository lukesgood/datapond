"""Masking policies could not be edited or turned off, and RLS roles could not be
changed after create (app/api/governance.py mask_update, role_lists)."""
import pytest
from fastapi import HTTPException

from app.api.governance import mask_update, role_lists


def test_mask_toggle_and_type():
    assert mask_update({"enabled": False}, "full") == {"enabled": False}
    assert mask_update({"masking_type": "hash"}, "custom") == {"masking_type": "hash", "custom_expression": None}


def test_mask_custom_needs_expression():
    with pytest.raises(HTTPException):
        mask_update({"masking_type": "custom"}, "full")
    with pytest.raises(HTTPException):
        mask_update({"custom_expression": "  "}, "custom")
    assert mask_update({"masking_type": "custom", "custom_expression": " upper(x) "}, "full") == \
        {"masking_type": "custom", "custom_expression": "upper(x)"}
    # Toggling a custom mask leaves its expression alone.
    assert mask_update({"enabled": True}, "custom") == {"enabled": True}


def test_mask_rejects_bad_values():
    for body in ({"masking_type": "rot13"}, {"enabled": "yes"}, {"custom_expression": 3}):
        with pytest.raises(HTTPException):
            mask_update(body, "full")


def test_role_lists():
    assert role_lists({"enabled": True}) is None
    assert role_lists({"role_names": [" a ", "b", ""], "exempt_role_names": ["b"]}) == (["a"], ["b"])
    assert role_lists({"exempt_role_names": []}) == ([], [])
    with pytest.raises(HTTPException):
        role_lists({"role_names": "a"})
