"""
Structured secret detection (regex, local).

Sits beside pii_ko and feeds the same pipeline: findings from here are merged into
pii_ko.detect(), so they go through one overlap resolver, one masker, and the mode
machinery already in place (off / mask / block, tightened per caller and per
collection). Every call site that guards PII today guards credentials too, with no
new wiring — ingest, search, RAG, AI-SQL, connector reads.

Why the guardrail and not a separate scanner: DataPond ingests company documents and
tables into collections and returns their content in cited answers. A document
carrying an AWS key or a database URL is embedded and handed back through exactly the
pipe that masks 주민등록번호 today. Detecting it anywhere else would be detecting it
after it has already left.

Precision over recall, deliberately. A guardrail that fires on ordinary text gets
turned off, and a guardrail that is off protects nothing. Every pattern here is either
structurally unmistakable (a PEM header, an AKIA-prefixed key id) or anchored to the
assignment that gives it meaning (`password = …`, `postgres://user:pw@host`).
Context-free high-entropy scanning is deliberately NOT included: it is the single
biggest source of false positives in this class of tool, and a base64 blob in a
document is far more often data than a credential.

Covered: 개인키(PEM), AWS 액세스 키, GitHub/Slack 토큰, JWT, DB 접속문자열의 비밀번호,
         이름이 붙은 자격증명 대입(api_key/secret/password/token = …).
"""
import re

# Values that look like credentials but are placeholders. Masking these would teach
# users the guardrail cries wolf, which is how guardrails get disabled.
_PLACEHOLDER = re.compile(
    r"""(?ix)
    ^(?:
        x{3,} | \*{3,} | \.{3,} | -{3,}          # xxxx, ****, ----
      | change[-_]?me | placeholder | redacted | secret | password
      | your[\w-]* | my[\w-]* | example[\w-]* | sample[\w-]* | dummy[\w-]* | test[\w-]*
                                                  # placeholder prefixes keep their
                                                  # hyphenated tails: example-value
      | none | null | nil | true | false | undefined
      | \$\{[^}]*\} | \$\([^)]*\) | \$\w+                # ${VAR}  $(VAR)  $VAR
      | <[^>]*> | \{\{[^}]*\}\} | %\w%                    # <your-key> {{key}} %KEY%
      | \[[^\]]+\]                                     # [자격증명] — already masked
    )$
    """)


def _not_placeholder(value: str) -> bool:
    return not _PLACEHOLDER.match((value or "").strip())


# (label, compiled regex, optional validator(value) -> bool, capture group)
# Group 0 masks the whole match; a non-zero group masks only the secret itself, so
# `password = "hunter2"` becomes `password = "[자격증명]"` and still reads as config.
_PATTERNS = [
    # A PEM header is never anything else.
    ("개인키", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"), None, 0),

    # AWS key ids carry a fixed 4-char type prefix and a 16-char body.
    ("AWS 액세스 키", re.compile(
        r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}\b"), None, 0),

    ("GitHub 토큰", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"), None, 0),
    ("Slack 토큰", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), None, 0),

    # header.payload.signature, where the header is the base64 of `{"`.
    ("JWT", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), None, 0),

    # RFI-05 calls this out by name: DB 접속 정보. Only the password is masked, so the
    # host and database stay readable — those are what makes the finding actionable.
    ("DB 접속정보", re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|mssql)"
        r"://[^\s:/@]+:([^\s@]{3,})@"), _not_placeholder, 1),

    # Named assignment. The name is the context that makes an otherwise ordinary
    # string a credential; without it this pattern would be entropy guessing.
    ("자격증명", re.compile(
        r"""(?ix)
        \b(?: api[-_]?key | secret[-_]?key | access[-_]?token | auth[-_]?token
            | client[-_]?secret | private[-_]?key | password | passwd | pwd )\b
        \s* [:=] \s* ["']? ([^\s"',;]{8,})
        """), _not_placeholder, 1),
]


def detect(text: str) -> list[dict]:
    """Findings in pii_ko's shape: {type, start, end, match}.

    Returned unresolved — pii_ko.detect() merges these with its own spans and runs
    one overlap pass over the union, so a secret inside a longer match resolves the
    same way two PII matches would.
    """
    if not text:
        return []
    out: list[dict] = []
    for label, rx, validator, group in _PATTERNS:
        for m in rx.finditer(text):
            try:
                value = m.group(group)
            except IndexError:  # pragma: no cover — group is a literal above
                continue
            if not value:
                continue
            if validator and not validator(value):
                continue
            out.append({"type": label, "start": m.start(group),
                        "end": m.end(group), "match": value})
    return out
