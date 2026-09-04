"""Did the person actually name this thing?

The assistant may not put a confirmation dialog in front of someone for a target
they never mentioned. What counts as "mentioned" is only ever something the USER
wrote — never something the assistant said, because the assistant repeats what it
read, and what it read includes table comments, column names and document chunks
that anyone with write access to a source can author.
"""
from app.chat.naming import named_by_user, normalise, segments


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text):
    return {"role": "assistant", "content": text}


def test_a_target_the_user_typed_is_named():
    ev = named_by_user("crm.customers", [_user("drop the crm.customers policy")])
    assert ev and ev["turn_index"] == 0


def test_a_target_only_the_assistant_mentioned_is_not_named():
    """The laundering case, and the reason this module exists."""
    assert named_by_user("crm.customers", [
        _user("clean up whatever looks unused"),
        _assistant("I found a policy on crm.customers that looks unused."),
    ]) is None


def test_a_target_nobody_mentioned_is_not_named():
    assert named_by_user("crm.customers", [_user("tidy up the policies")]) is None


def test_the_trailing_segment_counts():
    """People say "the customers policy", not "the crm.customers policy"."""
    assert named_by_user("crm.customers", [_user("delete the customers policy")])


def test_a_different_table_in_the_same_namespace_does_not_count():
    assert named_by_user("crm.customers", [_user("delete the crm.orders policy")]) is None


def test_case_quotes_and_backticks_do_not_matter():
    for written in ['delete `CRM.Customers`', 'delete "crm.customers"', "delete CRM.CUSTOMERS"]:
        assert named_by_user("crm.customers", [_user(written)]), written


def test_slash_and_colon_separate_too():
    assert named_by_user("iceberg:default/events", [_user("drop the events one")])


def test_the_evidence_names_the_turn_and_what_matched():
    """"Why was this allowed" is asked later, and the answer should not require
    reconstructing a conversation nobody kept."""
    ev = named_by_user("crm.customers", [_user("hi"), _user("delete crm.customers")])
    assert ev == {"turn_index": 1, "matched": "crm.customers"}


def test_an_empty_or_whitespace_target_is_never_named():
    """A target the server could not derive must not be waved through by a stray space."""
    for bad in ("", "   ", None):
        assert named_by_user(bad, [_user("delete everything")]) is None


def test_a_one_character_segment_does_not_match_by_accident():
    """Short segments would match almost any sentence; they need the whole name."""
    assert named_by_user("a.b", [_user("delete the b thing")]) is None
    assert named_by_user("a.b", [_user("delete a.b")])


def test_normalise_and_segments_are_the_documented_rule():
    assert normalise(' "CRM.Customers" ') == "crm.customers"
    assert segments("iceberg:default/events") == ["iceberg", "default", "events"]


def test_a_user_turn_with_tool_result_content_blocks_does_not_count():
    """Tool results ride under role: "user" and carry untrusted catalog text."""
    assert named_by_user("crm.customers", [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "content": "I found the policy on crm.customers"}
            ]
        }
    ]) is None


def test_a_user_turn_with_structured_content_dict_does_not_count():
    """Refuse to parse any structured content, not just lists."""
    assert named_by_user("crm.customers", [
        {"role": "user", "content": {"type": "text", "text": "delete crm.customers"}}
    ]) is None


def test_short_trailing_segments_collide_with_ordinary_words():
    """The minimum segment length raised to 4 prevents "ip" and "db" matching prose."""
    assert named_by_user("database.ip", [_user("clean up the ip in the report")]) is None
    assert named_by_user("database.ip", [_user("delete database.ip")])


def test_a_target_of_separators_only_has_no_segments():
    """Names like "..." or "///" normalise to empty segments and are rejected."""
    assert named_by_user("...", [_user("well ... maybe")]) is None
