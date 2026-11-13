"""Known sync failures, named, with what to do (design thinking C2). The live console
showed raw engine errors; 'payload changed type from row(...) to varchar' failed for two
days because nothing told the data engineer the fix."""
import pytest

from app.sync_diagnosis import diagnose

TYPE = ("Column 'payload' changed type from row(\"flags\" array(varchar), \"client\" varchar) to "
        "varchar; Iceberg cannot alter it in place. Drop the target table or sync into a new one.")


def test_a_type_change_offers_to_recreate_the_target():
    d = diagnose(TYPE)
    assert d["code"] == "type_change" and d["action"] == "recreate"
    assert "payload" in d["title"] and "row(" in d["detail"] and "varchar" in d["detail"]


@pytest.mark.parametrize("error,code,action", [
    ("Query engine restarting; retry in a minute", "engine_restarting", "retry"),
    ("line 1:15: Catalog 'src_crm' not found", "engine_restarting", "retry"),
    ("iceberg.default.orders is a read-only mirror of polaris_lake.default.orders: it is written "
     "through its owner catalog only.", "mirror_target", "change_target"),
    ('FATAL: password authentication failed for user "reader"', "auth_failed", "edit_connection"),
    ("Access denied for user 'reader'@'10.0.0.1' (using password: YES)", "auth_failed", "edit_connection"),
    ("Connection refused: db.example:5432", "unreachable", "check_connection"),
    ("connect timed out", "unreachable", "check_connection"),
    ("ERROR: permission denied for table payroll", "source_permission", "grant_source"),
])
def test_known_failures_are_named(error, code, action):
    d = diagnose(error)
    assert d["code"] == code and d["action"] == action and d["title"] and d["advice"]


def test_an_unknown_or_empty_error_has_no_diagnosis():
    assert diagnose("something unexpected") is None
    assert diagnose(None) is None and diagnose("") is None
