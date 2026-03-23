# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

"""Weather query skill for fetching daily weather information."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from agent.types import AgentTool, AgentToolResult, AbortSignal


# Common city coordinates fallback
CITY_COORDINATES = {
    "beijing": (39.9042, 116.4074),
    "shanghai": (31.2304, 121.4737),
    "guangzhou": (23.1291, 113.2644),
    "shenzhen": (22.5431, 114.0579),
    "chengdu": (30.5728, 104.0668),
    "wuhan": (30.5928, 114.3055),
    "chongqing": (29.5630, 105.9531),
    "tianjin": (39.3434, 117.3616),
    "nanjing": (32.0603, 118.7969),
    "xi'an": (34.3416, 108.9398),
    "hangzhou": (30.2741, 120.1551),
    "suzhou": (31.2989, 120.5853),
    "qingdao": (36.0671, 120.3826),
    "dalian": (38.9140, 121.6147),
    "tokyo": (35.6762, 139.6503),
    "osaka": (34.6937, 135.5023),
    "seoul": (37.5665, 126.9780),
    "bangkok": (13.7563, 100.5018),
    "singapore": (1.3521, 103.8198),
    "hanoi": (21.0285, 105.8542),
    "ho chi minh": (10.8231, 106.6297),
    "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "san francisco": (37.7749, -122.4194),
    "seattle": (47.6062, -122.3321),
    "boston": (42.3601, -71.0589),
    "washington": (38.9072, -77.0369),
    "miami": (25.7617, -80.1918),
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050),
    "rome": (41.9028, 12.4964),
    "madrid": (40.4168, -3.7038),
    "amsterdam": (52.3676, 4.9041),
    "moscow": (55.7558, 37.6173),
    "sydney": (-33.8688, 151.2093),
    "melbourne": (-37.8136, 144.9631),
    "dubai": (25.2048, 55.2708),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.7041, 77.1025),
}


@dataclass
class WeatherTool(AgentTool):
    """A tool to fetch weather information for a given location."""

    name: str = "weather_query"
    label: str = "Weather Query"
    description: str = (
        "Fetch daily weather information for a specified location. "
        "Returns temperature, conditions, and forecast for multiple days. "
        "Supports major cities worldwide."
    )
    api_key: str | None = None
    base_url: str = "https://api.open-meteo.com/v1/forecast"

    def _get_coordinates(self, location: str) -> tuple[float, float] | None:
        """Get coordinates for a location name."""
        # First check fallback dictionary
        location_lower = location.lower().strip()
        if location_lower in CITY_COORDINATES:
            return CITY_COORDINATES[location_lower]
        
        # Try to match partial names
        for city, coords in CITY_COORDINATES.items():
            if city in location_lower or location_lower in city:
                return coords
        
        # Try geocoding API as fallback
        geocode_url = f"https://nominatim.openstreetmap.org/search?format=json&q={location}&limit=1"
        try:
            req = urllib.request.Request(
                geocode_url,
                headers={"User-Agent": "py-twins-weather/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                if data:
                    return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception:
            pass
        
        return None

    def _fetch_weather(self, latitude: float, longitude: float, days: int = 7) -> dict[str, Any]:
        """Fetch weather data from Open-Meteo API."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,wind_speed_10m_max",
            "timezone": "auto",
            "forecast_days": days,
        }

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.base_url}?{query_string}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "py-twins-weather/1.0"})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Failed to fetch weather data: {e}") from e

    def _format_weather_code(self, code: int) -> str:
        """Convert WMO weather code to human-readable description."""
        weather_codes = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Foggy",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail",
        }
        return weather_codes.get(code, "Unknown")

    def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: AbortSignal | None = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        """
        Execute weather query for a location.

        Args:
            tool_call_id: Unique identifier for this tool call
            params: Dictionary containing:
                - location: Location name (required)
                - days: Number of forecast days (default: 7, max: 14)
            signal: Abort signal for cancellation
            on_update: Optional callback for progress updates

        Returns:
            AgentToolResult with formatted weather information
        """
        location = params.get("location")
        if not location:
            return AgentToolResult(
                content=[
                    {
                        "type": "text",
                        "text": "Error: 'location' parameter is required. Example: {'location': 'Beijing'}",
                    }
                ]
            )

        days = int(params.get("days", 7))
        days = min(max(days, 1), 14)  # Clamp between 1 and 14

        # Check for abort
        if signal and signal.aborted:
            return AgentToolResult(content=[{"type": "text", "text": "Request was aborted"}])

        # Get coordinates
        coords = self._get_coordinates(location)
        if not coords:
            supported_cities = ", ".join(sorted(CITY_COORDINATES.keys())[:10]) + "..."
            return AgentToolResult(
                content=[
                    {
                        "type": "text",
                        "text": f"Error: Could not find location '{location}'. Please use a city name. Supported cities include: {supported_cities}",
                    }
                ]
            )

        lat, lon = coords

        # Fetch weather data
        try:
            weather_data = self._fetch_weather(lat, lon, days)
        except RuntimeError as e:
            return AgentToolResult(content=[{"type": "text", "text": str(e)}])

        # Format the response
        daily = weather_data.get("daily", {})
        dates = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        codes = daily.get("weathercode", [])
        wind = daily.get("wind_speed_10m_max", [])

        forecast_lines = []
        for i, date_str in enumerate(dates[:days]):
            date = date_str[:10] if len(date_str) > 10 else date_str
            cond = self._format_weather_code(codes[i] if i < len(codes) else 0)
            t_max = temp_max[i] if i < len(temp_max) else None
            t_min = temp_min[i] if i < len(temp_min) else None
            p = precip[i] if i < len(precip) else 0
            w = wind[i] if i < len(wind) else None

            temp_str = f"{t_max:.0f}C / {t_min:.0f}C" if t_max is not None and t_min is not None else "N/A"
            precip_str = f"{p:.1f}mm" if p else "0mm"
            wind_str = f"{w:.1f} km/h" if w is not None else "N/A"

            forecast_lines.append(
                f"  {date}: {cond}, High/Low: {temp_str}, Precip: {precip_str}, Wind: {wind_str}"
            )

        current = weather_data.get("current", {})
        current_temp = current.get("temperature_2m")
        current_cond_code = current.get("weathercode")
        current_cond = self._format_weather_code(current_cond_code) if current_cond_code is not None else "Unknown"
        current_temp_str = f"{current_temp:.1f}C" if current_temp is not None else "N/A"

        response_text = (
            f"Weather forecast for {location} (Lat: {lat:.2f}, Lon: {lon:.2f}):\n\n"
            f"Current: {current_cond}, Temperature: {current_temp_str}\n\n"
            f"{days}-Day Forecast:\n" + "\n".join(forecast_lines)
        )

        return AgentToolResult(
            content=[{"type": "text", "text": response_text}],
            details={
                "location": location,
                "coordinates": {"latitude": lat, "longitude": lon},
                "forecast_days": days,
                "weather_data": weather_data,
            },
        )
