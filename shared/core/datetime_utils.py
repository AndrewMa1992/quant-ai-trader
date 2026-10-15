"""shared/core/datetime_utils.py – Market timezone and trading calendar utilities.

Handles timezone-aware date/time operations for five markets:
US (EST/EDT), HK (HKT), SG (SGT), AU (AEST/AEDT), NZ (NZST/NZDT).

Includes trading day detection, next/previous trading day lookups,
and market open/close time helpers.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# ── Market Timezone Mapping ──────────────────────────────────
MARKET_TIMEZONES: dict[str, str] = {
    "US": "America/New_York",
    "HK": "Asia/Hong_Kong",
    "SG": "Asia/Singapore",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
}

# ── Market Trading Hours (local time) ────────────────────────
MARKET_SCHEDULES: dict[str, dict[str, time]] = {
    "US": {
        "open": time(9, 30),
        "close": time(16, 0),
        "lunch_start": time(0, 0),  # No lunch break
    },
    "HK": {
        "open": time(9, 30),
        "close": time(16, 0),
        "lunch_start": time(12, 0),
        "lunch_end": time(13, 0),
    },
    "SG": {
        "open": time(9, 0),
        "close": time(17, 0),
        "lunch_start": time(12, 0),
        "lunch_end": time(13, 0),
    },
    "AU": {
        "open": time(10, 0),
        "close": time(16, 0),
        "lunch_start": time(0, 0),  # No lunch break
    },
    "NZ": {
        "open": time(10, 0),
        "close": time(16, 45),
        "lunch_start": time(0, 0),
    },
}


def market_timezone(market: str) -> ZoneInfo:
    """Get the ZoneInfo object for a market.

    Args:
        market: Market code (US/HK/SG/AU/NZ).

    Returns:
        ZoneInfo for the market's timezone.

    Raises:
        ValueError: If market code is unknown.
    """
    tz_name = MARKET_TIMEZONES.get(market.upper())
    if tz_name is None:
        raise ValueError(f"Unknown market: {market}. Valid: {list(MARKET_TIMEZONES.keys())}")
    return ZoneInfo(tz_name)


# ── Common Holidays (per market) ─────────────────────────────
US_HOLIDAYS: set[str] = {
    "01-01",   # New Year's Day
    "01-15", "01-16", "01-17", "01-18", "01-19", "01-20", "01-21",  # MLK Day (3rd Mon Jan approx)
    "02-19", "02-20", "02-21",  # Presidents' Day (3rd Mon Feb approx)
    "05-27", "05-28", "05-29", "05-30", "05-31",  # Memorial Day (last Mon May approx)
    "07-04",   # Independence Day
    "09-02", "09-03", "09-04",  # Labor Day (1st Mon Sep approx)
    "11-28", "11-29", "11-30",  # Thanksgiving (4th Thu Nov approx)
    "12-25",   # Christmas
}

HK_HOLIDAYS: set[str] = {
    "01-01",  # New Year's Day
    "02-10", "02-11", "02-12", "02-13",  # Lunar New Year (approx)
    "04-05",  # Ching Ming Festival (approx)
    "05-01",  # Labour Day
    "07-01",  # HKSAR Establishment Day
    "10-01",  # National Day
    "12-25", "12-26",  # Christmas
}

SG_HOLIDAYS: set[str] = {
    "01-01",  # New Year's Day
    "02-10", "02-11",  # Chinese New Year (approx)
    "03-29",  # Good Friday (approx)
    "05-01",  # Labour Day
    "08-09",  # National Day
    "12-25",  # Christmas
}

AU_HOLIDAYS: set[str] = {
    "01-01",  # New Year's Day
    "01-26",  # Australia Day
    "04-25",  # ANZAC Day
    "12-25", "12-26",  # Christmas
}

NZ_HOLIDAYS: set[str] = {
    "01-01", "01-02",  # New Year's
    "02-06",  # Waitangi Day
    "04-25",  # ANZAC Day
    "12-25", "12-26",  # Christmas
}

MARKET_HOLIDAYS: dict[str, set[str]] = {
    "US": US_HOLIDAYS,
    "HK": HK_HOLIDAYS,
    "SG": SG_HOLIDAYS,
    "AU": AU_HOLIDAYS,
    "NZ": NZ_HOLIDAYS,
}


def is_trading_day(check_date: date, market: str = "US") -> bool:
    """Check if a given date is a trading day for the specified market.

    A trading day is a weekday (Mon-Fri) that is not a market holiday.

    Args:
        check_date: The date to check.
        market: Market code.

    Returns:
        True if it's a trading day.
    """
    # Weekend check
    if check_date.weekday() >= 5:  # Saturday(5) or Sunday(6)
        return False

    # Holiday check (approximate MM-DD matching)
    holidays = MARKET_HOLIDAYS.get(market.upper(), set())
    mmdd = check_date.strftime("%m-%d")
    if mmdd in holidays:
        return False

    # Check for Good Friday (Friday before Easter — approximate)
    if market.upper() in ("HK", "SG", "AU"):
        pass  # Approximate holidays handled by the MM-DD set above

    return True


def next_trading_day(from_date: date, market: str = "US", skip: int = 1) -> date:
    """Find the next Nth trading day from a given date.

    Args:
        from_date: Starting date (exclusive – returns the next trading day).
        market: Market code.
        skip: Number of trading days to skip forward (default 1).

    Returns:
        The target trading date.
    """
    current = from_date + timedelta(days=1)
    found = 0
    while found < skip:
        if is_trading_day(current, market):
            found += 1
            if found == skip:
                return current
        current += timedelta(days=1)
    return current


def prev_trading_day(from_date: date, market: str = "US", skip: int = 1) -> date:
    """Find the previous Nth trading day from a given date.

    Args:
        from_date: Starting date (exclusive – returns the previous trading day).
        market: Market code.
        skip: Number of trading days to skip backward (default 1).

    Returns:
        The target trading date.
    """
    current = from_date - timedelta(days=1)
    found = 0
    while found < skip:
        if is_trading_day(current, market):
            found += 1
            if found == skip:
                return current
        current -= timedelta(days=1)
    return current


class MarketTimeHelper:
    """Utility class for market-specific time operations.

    Attributes:
        market: Market code.
        tz: ZoneInfo timezone for the market.
        schedule: Trading schedule dict.
    """

    def __init__(self, market: str) -> None:
        self.market = market.upper()
        if self.market not in MARKET_SCHEDULES:
            raise ValueError(f"Unknown market: {market}")
        self.tz = market_timezone(self.market)
        self.schedule = MARKET_SCHEDULES[self.market]

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Check if the market is currently open.

        Args:
            dt: Datetime to check (defaults to now in market timezone).

        Returns:
            True if market is open right now.
        """
        now = dt or datetime.now(self.tz)
        # Paper/demo: match pipeline market_session — US 24h is always open
        # (overnight LMT orders still reach the Tiger app).
        if self.market == "US":
            import os

            raw = os.getenv("QAT_US_24H_TRADING", "true").strip().lower()
            if raw in ("1", "true", "yes", "on", ""):
                return True
        if not is_trading_day(now.date(), self.market):
            return False

        open_time = self.schedule["open"]
        close_time = self.schedule["close"]
        current_time = now.time()

        # Lunch break
        lunch_start = self.schedule.get("lunch_start")
        lunch_end = self.schedule.get("lunch_end")
        if lunch_start and lunch_end and lunch_start != time(0, 0):
            if lunch_start <= current_time < lunch_end:
                return False

        return open_time <= current_time < close_time

    def time_to_open(self, dt: datetime | None = None) -> float:
        """Calculate seconds until market opens.

        Args:
            dt: Reference datetime (defaults to now).

        Returns:
            Seconds until next market open, or 0 if already open.
        """
        now = dt or datetime.now(self.tz)
        if self.is_market_open(now):
            return 0.0

        open_time = self.schedule["open"]
        target = now.replace(hour=open_time.hour, minute=open_time.minute, second=0, microsecond=0)

        if now.time() >= self.schedule["close"] or not is_trading_day(now.date(), self.market):
            # Find next trading day
            next_day = next_trading_day(now.date(), self.market)
            target = datetime.combine(next_day, open_time, tzinfo=self.tz)
        elif now.time() < open_time:
            target = datetime.combine(now.date(), open_time, tzinfo=self.tz)

        delta = (target - now).total_seconds()
        return max(delta, 0.0)

    def time_to_close(self, dt: datetime | None = None) -> float:
        """Calculate seconds until market closes.

        Args:
            dt: Reference datetime (defaults to now).

        Returns:
            Seconds until market close, or 0 if already closed.
        """
        now = dt or datetime.now(self.tz)
        if not self.is_market_open(now):
            return 0.0

        close_time = self.schedule["close"]
        target = now.replace(
            hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0
        )
        delta = (target - now).total_seconds()
        return max(delta, 0.0)

    @property
    def open_time_local(self) -> time:
        """Market open time in local timezone."""
        return self.schedule["open"]

    @property
    def close_time_local(self) -> time:
        """Market close time in local timezone."""
        return self.schedule["close"]
