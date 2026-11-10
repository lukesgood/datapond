"""Layer 2 (Trino file-based access control) learns which users may touch each source
catalog, so a caller who reaches Trino some other way meets the same wall the API
enforces (Phase 2 plan, Task 4)."""
from app.rls.trino_acl import generate_rules


def test_source_catalogs_become_a_catalogs_section_from_grants():
    rules = generate_rules([], [], [], source_catalogs={"src_crm": ["alice", "bob"],
                                                        "src_open": []})
    cats = rules["catalogs"]
    assert cats[0] == {"user": "^(alice|bob)$", "catalog": "^src_crm$", "allow": "read-only"}
    assert {"catalog": "^src_open$", "allow": "read-only"} in cats
    assert {"catalog": "^src_.*$", "allow": "none"} in cats and cats[-1] == {"allow": "all"}
    assert cats.index({"catalog": "^src_open$", "allow": "read-only"}) \
        < cats.index({"catalog": "^src_.*$", "allow": "none"})


def test_an_open_source_catalog_is_readable_by_everyone():
    rules = generate_rules([], [], [], source_catalogs={"src_open": []})
    assert {"catalog": "^src_open$", "allow": "read-only"} in rules["catalogs"]


def test_usernames_are_escaped_in_the_user_pattern():
    rules = generate_rules([], [], [], source_catalogs={"src_x": ["a.b", "c+d"]})
    assert rules["catalogs"][0]["user"] == r"^(a\.b|c\+d)$"


def test_without_source_catalogs_the_section_is_unchanged():
    assert generate_rules([], [], [])["catalogs"] == [{"allow": "all"}]
    assert generate_rules([], [], [], source_catalogs={})["catalogs"] == [{"allow": "all"}]


def test_source_catalog_tables_are_readable_by_granted_users_under_default_deny():
    """Table rules deny everything not explicitly allowed; a catalogs rule alone would
    let a granted user see src_crm and then be refused every table in it."""
    rules = generate_rules([], [], [], source_catalogs={"src_crm": ["alice"], "src_open": []})
    tables = rules["tables"]
    assert {"user": "^(alice)$", "catalog": "^src_crm$", "schema": ".*", "table": ".*",
            "privileges": ["SELECT"]} in tables
    assert {"catalog": "^src_open$", "schema": ".*", "table": ".*",
            "privileges": ["SELECT"]} in tables
    assert tables[-1]["privileges"] == []
