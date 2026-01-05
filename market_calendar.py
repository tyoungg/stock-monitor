"""
Market calendar utilities to check for trading days, hours, holidays, and half-days.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo
import holidays

NYSE_HOLIDAYS = holidays.financial_holidays("XNYS")
MARKET_TIMEZONE = ZoneInfo("America/New_York")

def is_market_holiday(check_date: date) -> bool:
    """Check if a given date is a NYSE holiday."""
    return check_date in NYSE_HOLIDAYS

def get_market_close_time(check_date: date) -> time:
    """Get the market close time for a given date, accounting for half-days."""
    holiday_name = NYSE_HOLIDAYS.get(check_date, "")
    if holiday_name and "early close" in holiday_name.lower():
        return time(13, 0)
    return time(16, 0)

def is_market_open(dt: datetime = None) -> bool:
    """
    Check if the market is open at a given datetime.
    If dt is None, it checks the current time.
    """
    if dt is None:
        dt = datetime.now(MARKET_TIMEZONE)
    else:
        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        dt = dt.astimezone(MARKET_TIMEZONE)

    d = dt.date()
    t = dt.time()

    if d.weekday() >= 5:  # Saturday or Sunday
        return False

    if is_market_holiday(d):
        return False

    market_open_time = time(9, 30)
    market_close_time = get_market_close_time(d)

    return market_open_time <= t < market_close_time

def is_pre_market(dt: datetime = None) -> bool:
    """Check if it is pre-market hours."""
    if dt is None:
        dt = datetime.now(MARKET_TIMEZONE)
    else:
        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        dt = dt.astimezone(MARKET_TIMEZONE)

    d = dt.date()
    t = dt.time()

    if d.weekday() >= 5 or is_market_holiday(d):
        return False

    pre_market_start = time(4, 0)
    market_open_time = time(9, 30)

    return pre_market_start <= t < market_open_time

def is_after_hours(dt: datetime = None) -> bool:
    """Check if it is after-hours."""
    if dt is None:
        dt = datetime.now(MARKET_TIMEZONE)
    else:
        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        dt = dt.astimezone(MARKET_TIMEZONE)

    d = dt.date()
    t = dt.time()

    if d.weekday() >= 5 or is_market_holiday(d):
        return False

    market_close_time = get_market_close_time(d)
    after_hours_end = time(20, 0)

    return market_close_time <= t < after_hours_end
