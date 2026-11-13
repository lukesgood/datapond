"""Known sync failures, named, with the action that fixes each (design thinking C2).

A sync error used to reach the console as the engine's raw message. The data engineer —
often the only one — had to know that "changed type … Iceberg cannot alter it in place"
means "drop the target and resync". `diagnose(error)` names the cause, says what to do,
and gives the console an `action` it can offer as a button:

- recreate          drop the target table and run a full sync (type change)
- retry             try again in a minute (engine restarting after a source change)
- change_target     sync into the owner catalog instead (target is a read-only mirror)
- edit_connection   fix the source credentials
- check_connection  check host, port, network path
- grant_source      grant the source user SELECT on the table

Unknown errors return None: the raw message is still shown.
"""
import re
from typing import Optional

_RULES = [
    (re.compile(r"Column '([^']+)' changed type from (.+?) to (.+?); Iceberg cannot alter", re.S),
     "type_change", "recreate",
     lambda m: f"Column '{m.group(1)}' changed type",
     lambda m: f"The lake table stores it as {m.group(2)}; the source now sends {m.group(3)}.",
     "Recreate the target table: it is dropped and fully re-synced from the source. Queries on "
     "it fail for the few seconds the sync takes."),
    (re.compile(r"engine restarting|Catalog '[^']*' (?:not found|does not exist)", re.I),
     "engine_restarting", "retry",
     lambda m: "Query engine is restarting",
     lambda m: "A source was added or changed, so Trino is reloading its catalogs (about a minute).",
     "Retry in a minute."),
    (re.compile(r"read-only mirror of ([\w.]+)", re.I),
     "mirror_target", "change_target",
     lambda m: "Target is a read-only mirror",
     lambda m: f"The table is written through its owner, {m.group(1)}.",
     "Set this table's target catalog to the owner's catalog, or sync into a new table."),
    (re.compile(r"password authentication failed|Access denied for user|Login failed for user|"
                r"Authentication failed", re.I),
     "auth_failed", "edit_connection",
     lambda m: "The source rejected the credentials",
     lambda m: "The user name or password stored for this source is no longer accepted.",
     "Edit the connection and update the password; then Check connection."),
    (re.compile(r"Connection refused|timed out|could not connect|Unknown host|"
                r"Name or service not known|No route to host", re.I),
     "unreachable", "check_connection",
     lambda m: "The source is unreachable",
     lambda m: "The engine could not open a connection to the source host.",
     "Check the host and port, that the database is running, and that the network allows "
     "the node to reach it; then Check connection."),
    (re.compile(r"permission denied for (?:table|relation|schema) (\S+)|SELECT command denied", re.I),
     "source_permission", "grant_source",
     lambda m: "The source user may not read this table",
     lambda m: "The database refused SELECT for the user this source connects as.",
     "Grant that user SELECT on the table in the source database, or exclude the table from sync."),
]


def diagnose(error: Optional[str]) -> Optional[dict]:
    if not error:
        return None
    for rx, code, action, title, detail, advice in _RULES:
        m = rx.search(str(error))
        if m:
            return {"code": code, "action": action, "title": title(m), "detail": detail(m), "advice": advice}
    return None
