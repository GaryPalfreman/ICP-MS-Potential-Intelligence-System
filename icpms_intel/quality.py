"""Conservative evidence checks: heuristics, never purchase probabilities."""
import re
from datetime import date


def source_relevance(text: str) -> float:
    if re.search(r"\bicp[\s–—-]*(?:ms|tof)\b|inductively coupled plasma|mass cytometry|\bcytof\b", text, re.I):
        return 0.85
    if re.search(r"elemental analys|trace element|mass spectrom", text, re.I):
        return 0.45
    return 0.15


def tender_state(row, today=None) -> str:
    today = today or date.today()
    status = str(row.get("notice_status", "")).lower()
    if status in {"closed", "cancelled", "awarded", "inactive"}:
        return "Closed / inactive"
    try:
        deadline = date.fromisoformat(str(row.get("response_deadline", ""))[:10])
    except ValueError:
        return "Unverified deadline"
    if deadline <= today:
        return "Closed / due today"
    return "Open" if status == "active" else "Unverified status"
