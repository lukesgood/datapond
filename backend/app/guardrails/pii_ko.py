"""
Korean PII guardrail (regex, local).

Runs in the DataPond backend *before* a prompt is forwarded to the LiteLLM gateway,
so raw PII never reaches a (possibly external) LLM provider — the privacy boundary
stays on-prem. Detects STRUCTURED Korean identifiers via regex (+ checksum where it
applies). Unstructured PII (names/addresses) needs an NER model and is out of scope.

Mode — env PII_GUARDRAIL_MODE:
  mask  (default) — replace each match with a "[유형]" tag
  block           — reject the request if any PII is found
  off             — passthrough

Covered: 주민/외국인등록번호(체크섬), 휴대전화, 사업자등록번호, 신용카드(Luhn),
         여권번호, 이메일. (계좌·운전면허는 오탐이 많아 기본 제외 — 필요 시 확장.)
"""
import os
import re
import logging

logger = logging.getLogger(__name__)

_RRN_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]


def _valid_rrn(value: str) -> bool:
    """주민/외국인등록번호 체크섬 검증 — 무작위 13자리 숫자의 오탐을 크게 줄인다."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 13:
        return False
    try:
        s = sum(int(d) * w for d, w in zip(digits[:12], _RRN_WEIGHTS))
        check = (11 - (s % 11)) % 10
        return check == int(digits[12])
    except Exception:
        return False


def _valid_luhn(value: str) -> bool:
    """신용카드 Luhn 검증."""
    digits = [int(c) for c in value if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# (label, compiled regex, optional validator(match_str) -> bool)
_PATTERNS = [
    ("주민등록번호", re.compile(r"\d{6}[-\s]?[1-8]\d{6}"), _valid_rrn),
    ("신용카드",     re.compile(r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{1,4}"), _valid_luhn),
    ("휴대전화",     re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"), None),
    ("사업자등록번호", re.compile(r"\d{3}-\d{2}-\d{5}"), None),
    ("여권번호",     re.compile(r"\b[MSRODGmsrodg]\d{8}\b"), None),
    ("이메일",       re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), None),
]


def detect(text: str) -> list[dict]:
    """Return non-overlapping PII findings (earliest, longest-first wins)."""
    if not text:
        return []
    spans: list[dict] = []
    for label, rx, validator in _PATTERNS:
        for m in rx.finditer(text):
            val = m.group(0)
            if validator and not validator(val):
                continue
            spans.append({"type": label, "start": m.start(), "end": m.end(), "match": val})
    # Resolve overlaps: sort by start, then longer match first; drop overlapping.
    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    out: list[dict] = []
    last_end = -1
    for s in spans:
        if s["start"] >= last_end:
            out.append(s)
            last_end = s["end"]
    return out


def mask(text: str, findings: list[dict] | None = None) -> str:
    """Replace each finding with a [유형] tag (offsets applied right-to-left)."""
    findings = findings if findings is not None else detect(text)
    out = text
    for f in sorted(findings, key=lambda x: x["start"], reverse=True):
        out = out[: f["start"]] + f"[{f['type']}]" + out[f["end"]:]
    return out


def get_mode() -> str:
    return (os.getenv("PII_GUARDRAIL_MODE", "mask") or "mask").strip().lower()


def apply(text: str) -> tuple[str, list[dict], bool]:
    """
    Process text per the configured mode.
    Returns (processed_text, findings, blocked).
    """
    if not text:
        return text, [], False
    mode = get_mode()
    if mode == "off":
        return text, [], False
    findings = detect(text)
    if not findings:
        return text, [], False
    if mode == "block":
        logger.info(f"[pii] blocked request — {len(findings)} PII finding(s): "
                    f"{sorted({f['type'] for f in findings})}")
        return text, findings, True
    masked = mask(text, findings)
    logger.info(f"[pii] masked {len(findings)} PII finding(s): "
                f"{sorted({f['type'] for f in findings})}")
    return masked, findings, False
