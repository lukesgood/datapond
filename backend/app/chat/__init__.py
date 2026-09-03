"""app.chat.actions and app.chat.analysis are mutually dependent: analysis modules
import Action/ActionKind/_Strict from actions, and actions loads its registry from
analysis (see actions.py's _load_actions). That resolves cleanly only when
app.chat.actions is the first of the two to start executing — importing it here,
before any submodule of this package, guarantees that ordering no matter which
submodule a caller reaches for first (e.g. `from app.chat import analysis`).
"""
from app.chat import actions  # noqa: F401
