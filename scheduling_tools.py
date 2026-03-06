"""
Date/scheduling helpers for the agent to plan when to place events. No file I/O.
"""

from datetime import date, timedelta
from typing import List


def avoid_weekends(dates: List[date]) -> List[date]:
    """Filter out Saturday (5) and Sunday (6)."""
    return [d for d in dates if d.weekday() < 5]


def dates_in_range(start_date: date, end_date: date) -> List[date]:
    """Return all dates from start_date through end_date."""
    out = []
    cur = start_date
    while cur <= end_date:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def exclude_weekday(dates: List[date], weekday: int) -> List[date]:
    """Exclude the given weekday (0=Monday .. 6=Sunday)."""
    return [d for d in dates if d.weekday() != weekday]


def schedule_evenly(
    clients: List[str],
    start_date: date,
    end_date: date,
    avoid_sat_sun: bool = True,
    exclude_weekdays: List[int] | None = None,
) -> List[tuple[str, date]]:
    """
    Distribute clients across weekdays in [start_date, end_date], one client per day.
    If avoid_sat_sun, skip weekends. If exclude_weekdays (0=Mon..6=Sun), skip those days.
    """
    all_dates = dates_in_range(start_date, end_date)
    if avoid_sat_sun:
        all_dates = avoid_weekends(all_dates)
    if exclude_weekdays:
        for wd in exclude_weekdays:
            all_dates = exclude_weekday(all_dates, wd)
    result = []
    for i, c in enumerate(clients):
        if i >= len(all_dates):
            break
        result.append((c, all_dates[i]))
    return result


def spread_events(dates: List[date], n: int) -> List[date]:
    """Pick n dates spread evenly across the list. If n >= len(dates), return all."""
    if not dates or n <= 0:
        return []
    if n >= len(dates):
        return list(dates)
    step = (len(dates) - 1) / (n - 1) if n > 1 else 0
    indices = [int(round(i * step)) for i in range(n)]
    return [dates[i] for i in indices]
