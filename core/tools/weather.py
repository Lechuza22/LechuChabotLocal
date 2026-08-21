from __future__ import annotations

import httpx

from core.tools import Tool, register

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WEATHER_CODES = {
    0: "despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con escarcha",
    51: "llovizna débil",
    53: "llovizna moderada",
    55: "llovizna intensa",
    56: "llovizna helada débil",
    57: "llovizna helada intensa",
    61: "lluvia débil",
    63: "lluvia moderada",
    65: "lluvia intensa",
    66: "lluvia helada débil",
    67: "lluvia helada intensa",
    71: "nevada débil",
    73: "nevada moderada",
    75: "nevada intensa",
    77: "granos de nieve",
    80: "chubascos débiles",
    81: "chubascos moderados",
    82: "chubascos violentos",
    85: "chubascos de nieve débiles",
    86: "chubascos de nieve intensos",
    95: "tormenta eléctrica",
    96: "tormenta eléctrica con granizo débil",
    99: "tormenta eléctrica con granizo intenso",
}


_WEATHER_EMOJI = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌦️",
    56: "🌦️",
    57: "🌦️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "❄️",
    73: "❄️",
    75: "❄️",
    77: "❄️",
    80: "🌦️",
    81: "🌦️",
    82: "🌧️",
    85: "🌨️",
    86: "🌨️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
}


def _describe(code: int | None) -> str:
    if code is None:
        return "desconocido"
    return _WEATHER_CODES.get(code, f"código {code}")


def _emoji(code: int | None) -> str:
    return _WEATHER_EMOJI.get(code, "🌡️")


def get_weather(location: str) -> dict:
    with httpx.Client(timeout=10.0) as client:
        geo_resp = client.get(
            GEOCODING_URL, params={"name": location, "count": 1, "language": "es", "format": "json"}
        )
        geo_resp.raise_for_status()
        results = geo_resp.json().get("results") or []
        if not results:
            return {"error": f"No se pudo encontrar la ubicación '{location}'."}
        place = results[0]
        lat, lon = place["latitude"], place["longitude"]

        forecast_resp = client.get(FORECAST_URL, params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 3,
        })
        forecast_resp.raise_for_status()
        forecast_data = forecast_resp.json()

    current = forecast_data.get("current", {})
    daily = forecast_data.get("daily", {})
    forecast_days = [
        {
            "date": date,
            "condition": _describe(code),
            "temp_min_c": temp_min,
            "temp_max_c": temp_max,
            "precipitation_probability_pct": precip,
        }
        for date, code, temp_min, temp_max, precip in zip(
            daily.get("time", []),
            daily.get("weather_code", []),
            daily.get("temperature_2m_min", []),
            daily.get("temperature_2m_max", []),
            daily.get("precipitation_probability_max", []),
        )
    ]

    return {
        "location": place.get("name"),
        "country": place.get("country"),
        "current": {
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "condition": _describe(current.get("weather_code")),
            "emoji": _emoji(current.get("weather_code")),
            "wind_speed_kmh": current.get("wind_speed_10m"),
        },
        "forecast": forecast_days,
    }


register(Tool(
    name="get_weather",
    description=(
        "Get current weather conditions and a 3-day forecast for a place, given its name "
        "(city, address, or landmark). Uses Open-Meteo, no API key required."
    ),
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "Place name, e.g. 'Buenos Aires' or 'Tigre, Argentina'"},
        },
        "required": ["location"],
    },
    func=get_weather,
))
