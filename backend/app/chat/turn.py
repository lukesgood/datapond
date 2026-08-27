"""Whether one user message may take another step.

The assistant answered a data question by calling catalog.find_tables and stopping.
It had found the table and never used it — one tool per turn, so the turn was over.

That rule was written for a reason the code states plainly: the assistant must not
chain work past a human. The reason is approval. A read runs without approval, so no
human was ever in that loop, and stopping after one protected nothing while costing
the answer the question asked for.

A turn therefore continues while the model keeps choosing reads and stops the moment
it proposes anything else — which is exactly where a person is supposed to decide.
"""
from typing import Optional

# Enough for discovery then work — find the table, describe it, write the SQL — and
# short enough that a model looping on the same call costs four requests, not forty.
DEFAULT_STEPS = 4


def should_continue(kind: Optional[str], status: Optional[str],
                    step: int, limit: int = DEFAULT_STEPS) -> bool:
    """May this turn ask the model again?

    `kind` — the action kind the model just chose, or None if it answered in prose.
    `status` — what the gate did with it.
    `step` — how many model calls this turn has already made.
    """
    if kind is None or step >= limit:
        return False
    if kind != "read":
        # Parked for approval. The next thing that happens is a person deciding, and
        # that is the boundary this whole design is built around.
        return False
    # A failed read repeated is the same failed read. Continuing invites the model to
    # try it again with the same arguments until the bound runs out.
    return status == "executed"
