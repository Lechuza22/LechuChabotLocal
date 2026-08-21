from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

IP_LOOKUP_URL = "https://ipwho.is/"
REVERSE_GEOCODE_URL = "https://nominatim.openstreetmap.org/reverse"
GPS_HELPER = Path(__file__).parent / "location_gps_helper.py"

_USER_AGENT = "Lechu/1.0 (local desktop assistant; personal use)"

_cached_ip: dict | None = None
_cached_gps: dict | None = None
_resolved_at: datetime | None = None


def resolve_location() -> dict | None:
    """Approximate, city-level location via IP geolocation. No key required."""
    global _cached_ip, _resolved_at
    try:
        resp = httpx.get(IP_LOOKUP_URL, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError:
        return None

    if not data.get("success", True):
        return None

    location = {
        "city": data.get("city"),
        "region": data.get("region"),
        "country": data.get("country"),
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "source": "ip",
    }
    if not location["city"]:
        return None

    _cached_ip = location
    _resolved_at = datetime.now()
    return location


def _reverse_geocode(lat: float, lon: float) -> dict | None:
    try:
        resp = httpx.get(
            REVERSE_GEOCODE_URL,
            params={"format": "json", "lat": lat, "lon": lon, "zoom": 12},
            headers={"User-Agent": _USER_AGENT},
            timeout=5.0,
        )
        resp.raise_for_status()
        address = resp.json().get("address", {})
    except httpx.HTTPError:
        return None

    city = address.get("city") or address.get("town") or address.get("village") or address.get("suburb")
    if not city:
        return None

    return {
        "city": city,
        "region": address.get("state"),
        "country": address.get("country"),
    }


def resolve_location_gps() -> dict | None:
    """Precise location via macOS CoreLocation (GPS/WiFi). Requires the user's Location
    Services permission - run as a subprocess since CoreLocation delegate callbacks only
    arrive on a thread with its own actively-pumped Cocoa run loop, which a run.io_bound
    worker thread inside the main app doesn't have (pywebview owns that thread's loop)."""
    global _cached_gps, _resolved_at
    try:
        proc = subprocess.run(
            [sys.executable, str(GPS_HELPER)], capture_output=True, text=True, timeout=12.0
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    try:
        coords = json.loads(proc.stdout)
    except ValueError:
        return None

    place = _reverse_geocode(coords["lat"], coords["lon"])
    if place is None:
        return None

    location = {**place, "lat": coords["lat"], "lon": coords["lon"], "source": "gps"}
    _cached_gps = location
    _resolved_at = datetime.now()
    return location


def get_cached_location() -> dict | None:
    return _cached_gps or _cached_ip
