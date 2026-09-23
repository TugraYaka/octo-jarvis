import json
import os
import time

USAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "search_usage.json")

FREE_MONTHLY_SEARCHES = 5000
MONTHLY_SAFETY_MARGIN = 200
MONTHLY_BUDGET = FREE_MONTHLY_SEARCHES - MONTHLY_SAFETY_MARGIN

INVOLVED_DAILY_LIMIT = 1500
INVOLVED_SAFETY_MARGIN = 100
INVOLVED_DAILY_BUDGET = INVOLVED_DAILY_LIMIT - INVOLVED_SAFETY_MARGIN

_DEFAULT = {"month": "", "month_count": 0, "day": "", "involved_count": 0}


def _current_month() -> str:
    return time.strftime("%Y-%m")


def _current_day() -> str:
    return time.strftime("%Y-%m-%d")


def _load() -> dict:
    data = dict(_DEFAULT)
    if os.path.exists(USAGE_PATH):
        try:
            with open(USAGE_PATH, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    if data.get("month") != _current_month():
        data["month"] = _current_month()
        data["month_count"] = 0
    if data.get("day") != _current_day():
        data["day"] = _current_day()
        data["involved_count"] = 0
    return data


def _save(data: dict) -> None:
    tmp_path = f"{USAGE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, USAGE_PATH)


def record_searches(queries: int) -> int:
    if queries <= 0:
        return _load()["month_count"]
    data = _load()
    data["month_count"] += queries
    _save(data)
    return data["month_count"]


def record_involved_request() -> int:
    data = _load()
    data["involved_count"] += 1
    _save(data)
    return data["involved_count"]


def searches_this_month() -> int:
    return _load()["month_count"]


def involved_requests_today() -> int:
    return _load()["involved_count"]
