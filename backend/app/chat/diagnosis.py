"""One shape for every composite diagnostic.

Three parts, and the split is the point. `facts` are measured. `signals` are judged —
by this server, against thresholds that live in code where a test can reach them, not
in a prompt where nothing can. `not_checked` is what was out of reach.

That last one is not decoration. A diagnosis that silently skips what it could not read
— an add-on that is off, a history table with no rows yet — is indistinguishable to the
model from one that found nothing wrong, and the model will report it as health.
"""
from typing import Any, Dict, List

SEVERITIES = ("ok", "warn", "bad")


class Diagnosis:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self._facts: Dict[str, Any] = {}
        self._signals: List[dict] = []
        self._not_checked: List[str] = []

    def fact(self, key: str, value: Any) -> "Diagnosis":
        self._facts[key] = value
        return self

    def signal(self, severity: str, statement: str, **evidence: Any) -> "Diagnosis":
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {severity!r}")
        self._signals.append({"severity": severity, "statement": statement,
                              "evidence": evidence})
        return self

    def skipped(self, reason: str) -> "Diagnosis":
        self._not_checked.append(reason)
        return self

    def done(self) -> dict:
        return {"subject": self.subject, "facts": dict(self._facts),
                "signals": list(self._signals), "not_checked": list(self._not_checked)}
