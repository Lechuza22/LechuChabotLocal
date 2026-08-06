from __future__ import annotations

import httpx

from core.secrets import get_secret
from core.tools import Tool, register

GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/{profile}"

SECRET_KEY = "maps_ors_api_key"

_PROFILES = {
    "driving": "driving-car",
    "walking": "foot-walking",
    "cycling": "cycling-regular",
}


def _geocode(client: httpx.Client, api_key: str, query: str) -> tuple[float, float, str] | None:
    resp = client.get(GEOCODE_URL, params={"api_key": api_key, "text": query, "size": 1})
    resp.raise_for_status()
    features = resp.json().get("features") or []
    if not features:
        return None
    feature = features[0]
    lon, lat = feature["geometry"]["coordinates"]
    label = feature["properties"].get("label", query)
    return lat, lon, label


def get_directions(origin: str, destination: str, mode: str = "driving") -> dict:
    api_key = get_secret(SECRET_KEY)
    if not api_key:
        return {
            "error": (
                "Conexión con Maps no configurada. Pedile al usuario que cargue su API key de "
                "OpenRouteService en Configuración → Conexiones → Maps."
            )
        }
    profile = _PROFILES.get(mode, _PROFILES["driving"])

    with httpx.Client(timeout=10.0) as client:
        origin_point = _geocode(client, api_key, origin)
        if origin_point is None:
            return {"error": f"No se pudo encontrar la ubicación de origen '{origin}'."}
        destination_point = _geocode(client, api_key, destination)
        if destination_point is None:
            return {"error": f"No se pudo encontrar la ubicación de destino '{destination}'."}

        origin_lat, origin_lon, origin_label = origin_point
        dest_lat, dest_lon, dest_label = destination_point

        directions_resp = client.get(
            DIRECTIONS_URL.format(profile=profile),
            params={
                "api_key": api_key,
                "start": f"{origin_lon},{origin_lat}",
                "end": f"{dest_lon},{dest_lat}",
            },
        )
        directions_resp.raise_for_status()
        directions_data = directions_resp.json()

    summary = directions_data["features"][0]["properties"]["summary"]
    return {
        "origin": origin_label,
        "destination": dest_label,
        "mode": mode,
        "distance_km": round(summary["distance"] / 1000, 1),
        "duration_min": round(summary["duration"] / 60),
    }


def test_connection() -> bool:
    """UI-only helper for the Configuración → Conexiones → Maps 'Probar conexión'
    button - not a registered LLM tool. Validates the currently saved key."""
    api_key = get_secret(SECRET_KEY)
    if not api_key:
        return False
    try:
        with httpx.Client(timeout=10.0) as client:
            return _geocode(client, api_key, "Buenos Aires") is not None
    except httpx.HTTPError:
        return False


register(Tool(
    name="get_directions",
    description=(
        "Get travel distance and estimated duration between two places by name, for driving, "
        "walking, or cycling. Uses OpenRouteService - requires an API key configured by the user "
        "in Configuración → Conexiones → Maps."
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "Starting place name or address"},
            "destination": {"type": "string", "description": "Destination place name or address"},
            "mode": {
                "type": "string",
                "enum": ["driving", "walking", "cycling"],
                "description": "Travel mode, defaults to driving",
            },
        },
        "required": ["origin", "destination"],
    },
    func=get_directions,
))
