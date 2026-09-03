"""Kept as the import path the routes already use. The implementations moved to
app/chat/analysis/, one module per domain — see that package's __init__."""
from app.chat.analysis import EXECUTORS, PREVIEWERS, RESOLVERS  # noqa: F401
