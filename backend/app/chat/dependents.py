"""What a destructive change will break.

Same split as app/chat/diagnosis.py, for the same reason: `items` are what was found,
`not_checked` is what was out of reach. An empty `items` with an empty `not_checked`
means "nothing depends on this" and is a claim. An empty `items` with a populated
`not_checked` means "I could not tell", which is a different card and a different
decision for the person reading it.
"""
from typing import Any, Dict, List


class Dependents:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self._items: List[dict] = []
        self._not_checked: List[str] = []

    def item(self, kind: str, name: str, effect: str) -> "Dependents":
        if not (kind or "").strip() or not (name or "").strip():
            raise ValueError("a dependent needs both a kind and a name")
        self._items.append({"kind": kind, "name": name, "effect": effect})
        return self

    def skipped(self, reason: str) -> "Dependents":
        self._not_checked.append(reason)
        return self

    def done(self) -> Dict[str, Any]:
        return {"subject": self.subject, "items": list(self._items),
                "not_checked": list(self._not_checked)}
