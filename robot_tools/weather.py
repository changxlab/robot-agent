"""Weather at the robot's site (`site` in robot.yaml) from Open-Meteo (free, no API key).

Read-only and real data in both modes: the weather does not come from the robot.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config
from .common import ToolError, Unavailable, header, kv

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 10.0
MAX_DAYS = 3
CURRENT = ("temperature_2m", "relative_humidity_2m", "apparent_temperature", "precipitation",
           "weather_code", "wind_speed_10m", "wind_direction_10m")
DAILY = ("weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
         "precipitation_probability_max", "uv_index_max", "sunrise", "sunset")
# WMO weather interpretation codes used by Open-Meteo.
WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
    48: "depositing rime fog", 51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "light freezing rain", 67: "freezing rain", 71: "light snow",
    73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light rain showers",
    81: "rain showers", 82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def site() -> dict[str, Any]:
    return config.load()["site"]


def fetch(days: int) -> dict[str, Any]:
    s = site()
    query = urllib.parse.urlencode({
        "latitude": s["latitude"], "longitude": s["longitude"], "timezone": s["timezone"],
        "current": ",".join(CURRENT), "daily": ",".join(DAILY), "forecast_days": days,
    })
    try:
        with urllib.request.urlopen(f"{URL}?{query}", timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise Unavailable(f"no weather data from Open-Meteo ({exc}); the robot computer needs "
                          "internet access") from exc


def _sky(code: Any) -> str:
    return WMO.get(code, f"weather code {code}")


def _compass(deg: float) -> str:
    return COMPASS[round(deg / 45) % 8]


def _clock(iso: str) -> str:
    return iso.split("T")[-1]


def print_weather(data: dict[str, Any], days: int) -> None:
    s = site()
    try:
        now = datetime.now(ZoneInfo(s["timezone"]))
    except ZoneInfoNotFoundError:
        now = datetime.now()
    header(f"Weather - {s['name']}", real=True)
    kv("local time", now.strftime("%A %Y-%m-%d %H:%M"))
    c = data.get("current") or {}
    if c:
        kv("now", f"{c['temperature_2m']} C (feels {c['apparent_temperature']} C), "
                  f"{_sky(c['weather_code'])}, humidity {c['relative_humidity_2m']}%, "
                  f"wind {c['wind_speed_10m']} km/h {_compass(c['wind_direction_10m'])}, "
                  f"precipitation {c['precipitation']} mm")
    d = data.get("daily") or {}
    for i, date in enumerate((d.get("time") or [])[:days]):
        label = "today" if i == 0 else ("tomorrow" if i == 1 else date)
        kv(label, f"{date}: {_sky(d['weather_code'][i])}, {d['temperature_2m_min'][i]}.."
                  f"{d['temperature_2m_max'][i]} C, rain {d['precipitation_sum'][i]} mm "
                  f"({d['precipitation_probability_max'][i]}% chance), "
                  f"UV {d['uv_index_max'][i]}, sunrise {_clock(d['sunrise'][i])}, "
                  f"sunset {_clock(d['sunset'][i])}")
    if s.get("description"):
        kv("site", s["description"])
    print("source: Open-Meteo (open-meteo.com)")


def cmd(args) -> int:
    if not 1 <= args.days <= MAX_DAYS:
        raise ToolError(f"--days must be between 1 and {MAX_DAYS}")
    print_weather(fetch(args.days), args.days)
    return 0


def register(sub) -> None:
    p = sub.add_parser("weather", help="current weather and forecast at the robot's site")
    p.add_argument("--days", type=int, default=1, help=f"forecast days (1-{MAX_DAYS})")
    p.set_defaults(func=cmd)
