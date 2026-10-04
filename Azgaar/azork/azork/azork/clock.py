"""Daylight and the plan clock.

Simplified sunrise model: solar declination from the day of the year, hour angle
from latitude, local solar time only (no equation of time, no refraction, no
twilight). Azgaar calendars carry only a year, so the journey's starting day of
the year comes from the world's content pack; the default is the spring equinox,
where dawn is 06:00 and dusk 18:00 at every latitude.

Plan rules (time t is hours since dawn of journey day 1):
  * a stay starts on arrival and lasts its duration;
  * a stage with fewer than 24 travel hours a day departs at the next dawn and spreads
    its daily travel hours across the daylight, so a full day ends at dusk;
  * a 24-hour mode (sailing ship, airship) departs on arrival and never stops.
"""
from __future__ import annotations

import math

EQUINOX = 80  # day of year
GRACE = 0.25  # hours: arriving this soon after dawn still counts as departing at dawn


def latitude(m, y: float) -> float:
    co = m.settings["geography"]["coordinates"]
    return co["latN"] - y / m.settings["graph"]["height"] * co["latT"]


def daylight(lat: float, day_of_year: int) -> tuple[float, float]:
    """(dawn, dusk) in local solar hours; polar day/night clamp to 0..24."""
    decl = -23.44 * math.cos(2 * math.pi * (day_of_year + 10) / 365)
    x = -math.tan(math.radians(lat)) * math.tan(math.radians(decl))
    if x <= -1:
        return 0.0, 24.0
    if x >= 1:
        return 12.0, 12.0
    half = math.degrees(math.acos(x)) / 15
    return 12 - half, 12 + half


class PlanClock:
    """t = hours since dawn of journey day 1 at the starting latitude."""

    def __init__(self, start_lat: float, start_day_of_year: int = EQUINOX):
        self.start_doy = start_day_of_year
        self.origin = daylight(start_lat, start_day_of_year)[0]

    def doy(self, day0: int) -> int:
        """Day of year for a 0-based journey day index."""
        return (self.start_doy - 1 + day0) % 365 + 1

    def abs_hour(self, t: float) -> float:
        """Hours since midnight before journey day 1."""
        return self.origin + t

    def next_dawn(self, t: float, lat: float) -> float:
        """Plan time of the first dawn at or after t, at latitude lat."""
        h = self.abs_hour(t)
        day0 = int(h // 24)
        for d in (day0, day0 + 1):
            dawn, dusk = daylight(lat, self.doy(d))
            if dusk > dawn and d * 24 + dawn >= h - GRACE:
                return t + max(0.0, d * 24 + dawn - h)
        return t  # polar night: travel anyway

    def travel(self, t_start: float, travel_hours: float, hours_per_day: float, lat: float) -> float:
        """Plan time of arrival for a moving stage."""
        if hours_per_day >= 24:
            return t_start + travel_hours
        t = self.next_dawn(t_start, lat)
        left = travel_hours
        while True:
            dawn, dusk = daylight(lat, self.doy(int(self.abs_hour(t) // 24)))
            light = max(dusk - dawn, 1e-6)
            if left <= hours_per_day + 1e-9:
                return t + left / hours_per_day * light
            left -= hours_per_day
            t = self.next_dawn(t + light + 1e-6, lat)

    def label(self, t: float, lat: float) -> str:
        h = self.abs_hour(t)
        day0, hour = int(h // 24), h % 24
        hh, mm = int(hour), int(round((hour - int(hour)) * 60))
        if mm == 60:
            hh, mm = hh + 1, 0
        dawn, dusk = daylight(lat, self.doy(day0))
        part = ("night" if hour < dawn - 0.5 or hour > dusk + 0.5 else
                "dawn" if hour < dawn + 1 else "dusk" if hour > dusk - 1 else "day")
        return f"day {day0 + 1}, {hh:02d}:{mm:02d} ({part})"
