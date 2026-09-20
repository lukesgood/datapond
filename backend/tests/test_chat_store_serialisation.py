"""What the gate stores has to survive the round trip, not merely avoid an exception.

Live, asking the assistant "서비스 상태 알려줘" produced no answer at all. The model
chose the right tool, the tool ran, and the result — {"health": ServiceHealth(...)} —
reached store.update, where json.dumps refused it: "Object of type ServiceHealth is not
JSON serializable". gate._execute wraps only the executor call, so the failure surfaced
as a refusal with nothing rendered.

Fifteen of the forty executors hand back something other than a dict literal, so this
is a property of the storage boundary rather than of one tool. The assertions below are
about the *fields* rather than about not raising: str(model) would also stop the
exception and would put "ServiceHealth(service='backend'…)" on the user's screen, which
is worse than the crash because it looks like it worked.
"""
import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel

from app.chat.store import to_jsonable


class Health(BaseModel):
    service: str
    pods_ready: int
    last_restart: str | None = None


def _round_trip(value):
    return json.loads(json.dumps(to_jsonable(value), default=str))


def test_a_model_keeps_its_fields():
    out = _round_trip({"health": Health(service="backend", pods_ready=2)})
    assert out["health"]["service"] == "backend"
    assert out["health"]["pods_ready"] == 2


def test_a_model_nested_in_a_list_keeps_its_fields():
    out = _round_trip({"services": [Health(service="litellm", pods_ready=1),
                                    Health(service="valkey", pods_ready=0)]})
    assert [s["service"] for s in out["services"]] == ["litellm", "valkey"]


def test_a_bare_model_is_not_stringified():
    """str(model) would silence the crash and render as prose nobody can read."""
    out = _round_trip(Health(service="mlflow", pods_ready=1))
    assert isinstance(out, dict) and out["service"] == "mlflow"


def test_plain_values_are_untouched():
    payload = {"events": {"counts": {"info": 1, "warning": 12}}, "ok": True, "n": None}
    assert _round_trip(payload) == payload


def test_types_json_cannot_hold_fall_back_to_text():
    """datetimes and UUIDs reach here from route handlers; the codebase's convention
    elsewhere is default=str rather than a bespoke encoder."""
    out = _round_trip({"at": datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc),
                       "id": UUID("00000000-0000-0000-0000-000000000001")})
    assert out["at"].startswith("2026-09-21")
    assert out["id"] == "00000000-0000-0000-0000-000000000001"


def test_none_stays_none():
    assert to_jsonable(None) is None
