"""Weather from Open-Meteo: free, no key, no account. "What's the weather?", "will it rain in Dubai tomorrow?"."""
import httpx

from ..config import settings

_CODES = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
          51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
          71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent showers",
          95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}
UA = {"User-Agent": "JarvisAssistant/1.0 (personal desktop assistant)"}


def _place(name):
    r = httpx.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": name, "count": 1}, headers=UA, timeout=10)
    hits = r.json().get("results") or []
    if not hits:
        raise RuntimeError(f"I couldn't find a place called {name}.")
    h = hits[0]
    return h["latitude"], h["longitude"], ", ".join(x for x in (h["name"], h.get("country")) if x)


def forecast(place=""):
    place = (place or settings.get("weather_place") or "").strip()
    if not place:
        return "Which city? You can also set your home city under Settings."
    lat, lon, label = _place(place)
    d = httpx.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=10, params={
        "latitude": lat, "longitude": lon, "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "auto", "forecast_days": 2}).json()
    c, day = d["current"], d["daily"]
    now = _CODES.get(c["weather_code"], "mixed conditions")
    tmr = _CODES.get(day["weather_code"][1], "mixed conditions")
    return (f"In {label} it's {c['temperature_2m']:.0f}°C and {now}, feeling like {c['apparent_temperature']:.0f}°C. "
            f"Today: high {day['temperature_2m_max'][0]:.0f}°, low {day['temperature_2m_min'][0]:.0f}°, "
            f"{day['precipitation_probability_max'][0]}% chance of rain. "
            f"Tomorrow: {tmr}, up to {day['temperature_2m_max'][1]:.0f}°.")
