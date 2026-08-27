"""What a migration has to say about itself before it is safe to review.

`helm --atomic` rolls back the release, not the database. A migration that ran before
a failed deploy leaves old code against a new schema, and nothing in the tooling
prevents it. Expand/contract does — add in one release, remove in a later one — and
that is a discipline rather than a feature.

A check cannot know whether dropping a column is safe: that depends on which code is
still running, which is not in the file. What it can do is refuse to let the question
go unasked. A migration that removes something must name the earlier revision that
stopped using it, which turns "someone should have thought about this" into a sentence
a reviewer can agree or disagree with — and which is wrong in a way that can be
checked, unlike silence.
"""
import re
from dataclasses import dataclass
from typing import List

# The first revision builds a schema from nothing. There is no previous release for
# it to be compatible with, so the rule does not apply.
EXEMPT = ("0001_baseline",)

MARKER = "Contract-of"

# Each rule is (pattern, what it breaks). Deliberately narrow: a check that fires on
# safe changes is a check people learn to bypass.
_RULES = [
    (re.compile(r"\bDROP\s+TABLE\b", re.I),
     "removes a table the previous release may still read"),
    (re.compile(r"\bDROP\s+COLUMN\b", re.I),
     "removes a column the previous release may still select or insert"),
    (re.compile(r"\bRENAME\s+(TO|COLUMN)\b", re.I),
     "renames — the previous release looks for the old name and finds nothing. There "
     "is no version of a rename that is safe in one release; add, backfill, remove"),
    (re.compile(r"\bSET\s+NOT\s+NULL\b", re.I),
     "makes an existing column required, so inserts from the previous release start "
     "failing while the deploy still looks successful. NOT NULL needs its own release "
     "after everything writes the column"),
]


@dataclass(frozen=True)
class Violation:
    statement: str
    message: str


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return "\n".join(line.split("--", 1)[0] for line in sql.split("\n"))


def review_migration(revision: str, sql: str, docstring: str = "") -> List[Violation]:
    """Anything in `sql` that needs the migration to have said something first.

    `docstring` is the revision file's own text; a `Contract-of: <revision>` line in
    it satisfies every rule below. One line covers the whole file on purpose — the
    reviewer reads the file, and a per-statement annotation would be noise that
    teaches people to paste it.
    """
    if revision in EXEMPT or MARKER.lower() in (docstring or "").lower():
        return []

    body = _strip_comments(sql)
    out = []
    for pattern, why in _RULES:
        for match in pattern.finditer(body):
            line = body[body.rfind("\n", 0, match.start()) + 1:
                        (body.find("\n", match.end()) + 1 or len(body))]
            out.append(Violation(
                statement=line.strip(),
                message=(f"{match.group(0).upper()} {why}. If the previous release "
                         f"already stopped using it, say so: a `{MARKER}: <revision>` "
                         f"line in this file's docstring."),
            ))
    return out
