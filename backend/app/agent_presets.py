"""Purpose presets for a new agent (service account) — pure, no I/O.

Creating an agent meant choosing a role from seven and then, on a second screen,
ticking scopes from up to eighteen. The default role was `ai_engineer`, and a key
issued with no scope ticked gets every permission of the role — so the path of least
effort was the widest credential on offer. A preset names what the agent is for and
fills in the narrowest role, key scopes and PII guardrail that serve it.

A preset is a starting point, not a type: nothing records which one was used, and
everything it set can be changed afterwards on the agent's page. It also cannot widen
anything — the scopes are intersected with the role like any other key's
(`service_accounts.effective_permissions`), and the PII mode can only tighten the
deployment default (`guardrails/pii_ko.tighten`).
"""
from dataclasses import dataclass
from typing import Optional, Tuple

PII_MODES = ("off", "mask", "block")


@dataclass(frozen=True)
class AgentPreset:
    id: str
    label: str
    description: str
    role: str
    scopes: Tuple[str, ...]
    pii_mode: Optional[str]   # None inherits the deployment default

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description,
                "role": self.role, "scopes": list(self.scopes), "pii_mode": self.pii_mode}


PRESETS: Tuple[AgentPreset, ...] = (
    AgentPreset(
        id="knowledge_assistant",
        label="Document Q&A",
        description="Answers questions from Knowledge collections with citations — "
                    "a support or internal help bot. Reads only the collections you "
                    "grant it; cannot run SQL.",
        role="ai_engineer",
        scopes=("knowledge:read", "ai:generate"),
        pii_mode="mask",
    ),
    AgentPreset(
        id="metrics_reader",
        label="Metrics and SQL reader",
        description="Reads approved metrics and runs read-only SQL over the catalog. "
                    "No model spend, no Knowledge access.",
        role="business_analyst",
        scopes=("catalog:read", "query:run"),
        pii_mode="mask",
    ),
    AgentPreset(
        id="analysis_assistant",
        label="Analysis assistant",
        description="Natural-language questions over tables and documents: NL→SQL, "
                    "metrics, cited Knowledge answers, source freshness. Reads only.",
        role="data_scientist",
        scopes=("catalog:read", "query:run", "knowledge:read", "ai:generate",
                "connector:read"),
        pii_mode="mask",
    ),
    AgentPreset(
        id="pipeline_operator",
        label="Pipeline operator",
        description="Runs and watches source syncs from a scheduler or CI job. "
                    "No model spend, no Knowledge access.",
        role="data_engineer",
        scopes=("catalog:read", "connector:read", "connector:write", "query:run"),
        pii_mode=None,
    ),
)

_BY_ID = {p.id: p for p in PRESETS}


def get_preset(preset_id: str) -> Optional[AgentPreset]:
    return _BY_ID.get(preset_id)


def valid_pii_mode(value: object) -> bool:
    """None (inherit) or one of the modes the users.pii_mode CHECK accepts."""
    return value is None or value in PII_MODES
