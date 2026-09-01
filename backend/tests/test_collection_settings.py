"""Creating and managing a collection with real choices.

Creation took a name and a description. Everything that changes how the collection
behaves — how documents are split, who else can read it — was either a fixed default
or reachable only by accident.

Chunking is the one that matters most and was the most hidden: it is a per-request
parameter on ingest with a default of 1000/150, and the UI never sent it. So every
collection had the same split whether it held one-line FAQ entries or contracts, and
two ingests into the same collection could silently use different sizes.

Two things deliberately NOT offered as choices, because the product cannot honour
them: the embedding model and its dimension. `ai_chunks.embedding` is a single
`vector(n)` column shared by every collection, so a per-collection model is not a
setting, it is a schema change. Offering the choice would be a lie the user only
discovers when retrieval returns nothing.
"""
import pytest

from app.api.ai_vectors import CHUNK_PRESETS, resolve_chunking


def test_a_named_preset_resolves_to_its_numbers():
    assert resolve_chunking("standard", None, None) == (1000, 150)


def test_every_preset_is_usable():
    for name in CHUNK_PRESETS:
        size, overlap = resolve_chunking(name, None, None)
        assert size > 0 and 0 <= overlap < size, name


def test_overlap_is_always_smaller_than_the_chunk():
    """An overlap at or above the chunk size makes _chunk() advance by zero or go
    backwards — an ingest that never terminates."""
    for name, (size, overlap) in CHUNK_PRESETS.items():
        assert overlap < size, name


def test_custom_numbers_win_over_the_preset():
    assert resolve_chunking("standard", 300, 40) == (300, 40)


def test_an_unknown_preset_falls_back_to_standard_rather_than_failing():
    """A collection created by an older client, or a preset renamed later, must
    still ingest."""
    assert resolve_chunking("no-such-preset", None, None) == (1000, 150)


def test_overriding_one_number_keeps_the_preset_it_was_chosen_with():
    """The half that was not given comes from the preset the caller picked, not from
    the default one. Otherwise choosing "long" and nudging the overlap silently
    halves the chunk size to standard's, and the collection is then stored claiming
    a preset its numbers do not match — the UI says "Long documents" while ingest
    splits at 1000."""
    assert resolve_chunking("long", None, 250) == (2000, 250)
    assert resolve_chunking("short", 400, None) == (400, 0)
    # An unknown preset still falls back to the default, as above.
    assert resolve_chunking("no-such-preset", None, 250) == (1000, 250)


def test_nothing_specified_is_standard():
    assert resolve_chunking(None, None, None) == (1000, 150)


def test_a_custom_overlap_that_would_not_terminate_is_refused():
    with pytest.raises(ValueError):
        resolve_chunking(None, 200, 200)


def test_a_negative_size_is_refused():
    with pytest.raises(ValueError):
        resolve_chunking(None, 0, 0)


def test_the_presets_span_a_useful_range():
    """Three sizes that mean something different, not three names for the same
    number."""
    sizes = sorted(s for s, _o in CHUNK_PRESETS.values())
    assert sizes[0] * 2 <= sizes[-1]
