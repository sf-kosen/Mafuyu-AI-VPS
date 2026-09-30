"""get_weather tool: Japan Meteorological Agency (気象庁) forecasts.

Uses JMA's public JSON (no API key). A place name such as "藤沢", "神奈川県", or
"京都" is resolved to a forecast office and, when a city matches, its sub-area.
"""

import logging
import re
import time
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{code}.json"
AREA_TTL_SEC = 24 * 3600
TIMEOUT_SEC = 10
WEEKDAYS = "月火水木金土日"

# Places whose name doesn't match a single forecast office by itself.
ALIASES = {"北海道": "016000", "札幌": "016000", "沖縄": "471000", "那覇": "471000"}
_PREF_SUFFIX = re.compile(r"(都|府|県)$")
_CITY_SUFFIX = re.compile(r"(市|区|町|村)$")

GET_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "気象庁の天気予報（今日〜明後日の天気・降水確率・気温と、週間の降水確率・気温）を取得する。"
            "日本国内の天気を聞かれたらweb_searchではなくこれを使う。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "place": {
                    "type": "string",
                    "description": "地名（市区町村名や都道府県名。例: 藤沢市、神奈川県、京都）",
                },
            },
            "required": ["place"],
        },
    },
}


def _day_label(iso: str) -> str:
    t = datetime.fromisoformat(iso)
    return f"{t.month}/{t.day}({WEEKDAYS[t.weekday()]})"


def _clean(text: str) -> str:
    return text.replace("　", "")


def resolve_place(areas: dict, place: str) -> tuple[str, str | None, str] | None:
    """Return (office code, class10 sub-area code or None, matched name) for a place."""
    p = re.sub(r"(の天気|の予報|天気|予報)$", "", place.replace(" ", "").replace("　", ""))
    if not p:
        return None
    if p in ALIASES:
        return ALIASES[p], None, p

    offices = areas["offices"]
    prefs = {code: info["name"] for code, info in offices.items() if info["name"][-1] in "都府県"}
    # Full names first: "東京都" contains "京都", so the bare-name match alone is ambiguous.
    pref_code = next((c for c, n in prefs.items() if n in p), None)
    if pref_code is None:
        pref_code = next((c for c, n in prefs.items() if _PREF_SUFFIX.sub("", n) in p), None)

    class10s, class15s, class20s = areas["class10s"], areas["class15s"], areas["class20s"]
    best = None
    for info in class20s.values():
        name = info["name"]
        base = _CITY_SUFFIX.sub("", name)
        if not (p == base or p == name or (len(base) >= 2 and base in p)):
            continue
        class10 = class15s.get(info["parent"], {}).get("parent")
        office = class10s.get(class10, {}).get("parent") if class10 else None
        if not office or (pref_code and office != pref_code):
            continue
        if best is None or len(base) > best[3]:
            best = (office, class10, name, len(base))
    if best:
        return best[0], best[1], best[2]
    if pref_code:
        return pref_code, None, offices[pref_code]["name"]
    for code, info in offices.items():  # e.g. "十勝地方"
        if _clean(info["name"]).removesuffix("地方") in p:
            return code, None, info["name"]
    return None


def format_forecast(data: list, class10: str | None) -> str:
    short = data[0]
    series = short["timeSeries"]
    lines = [f"{short['publishingOffice']} {_day_label(short['reportDatetime'])}"
             f"{datetime.fromisoformat(short['reportDatetime']).hour}時発表"]

    wanted = [a for a in series[0]["areas"] if class10 is None or a["area"]["code"] == class10]
    wanted = wanted or series[0]["areas"]
    codes = {a["area"]["code"] for a in wanted}
    for area in wanted:
        lines.append(f"【{area['area']['name']}】")
        for t, w in zip(series[0]["timeDefines"], area.get("weathers", [])):
            lines.append(f"{_day_label(t)} {_clean(w)}")
        for pop_area in series[1]["areas"]:
            if pop_area["area"]["code"] == area["area"]["code"]:
                pops = [
                    f"{_day_label(t)}{datetime.fromisoformat(t).hour}時〜 {p}%"
                    for t, p in zip(series[1]["timeDefines"], pop_area["pops"]) if p
                ]
                lines.append("降水確率: " + " / ".join(pops))

    if len(series) > 2:
        temps = []
        for point in series[2]["areas"]:
            vals = []
            for t, v in zip(series[2]["timeDefines"], point.get("temps", [])):
                hour = datetime.fromisoformat(t).hour
                kind = "最低" if hour < 9 else "最高"
                vals.append(f"{_day_label(t)}{kind}{v}℃")
            temps.append(f"{point['area']['name']}: " + " ".join(vals))
        lines.append("気温: " + " / ".join(temps))

    if len(data) > 1:  # weekly forecast
        weekly = data[1]["timeSeries"]
        area = next((a for a in weekly[0]["areas"] if a["area"]["code"] in codes), weekly[0]["areas"][0])
        pops = [f"{_day_label(t)} {p}%" for t, p in zip(weekly[0]["timeDefines"], area.get("pops", [])) if p]
        if pops:
            lines.append("週間の降水確率: " + " / ".join(pops))
        if len(weekly) > 1 and weekly[1]["areas"]:
            point = weekly[1]["areas"][0]
            temps = [
                f"{_day_label(t)} {lo}〜{hi}℃"
                for t, lo, hi in zip(weekly[1]["timeDefines"], point.get("tempsMin", []), point.get("tempsMax", []))
                if lo and hi
            ]
            if temps:
                lines.append(f"週間の気温（{point['area']['name']}）: " + " / ".join(temps))
    return "\n".join(lines)


class WeatherClient:
    def __init__(self):
        self._areas: dict | None = None
        self._areas_at = 0.0

    async def _get_areas(self, client: httpx.AsyncClient) -> dict:
        if self._areas is None or time.monotonic() - self._areas_at > AREA_TTL_SEC:
            resp = await client.get(AREA_URL)
            resp.raise_for_status()
            self._areas = resp.json()
            self._areas_at = time.monotonic()
        return self._areas

    async def get_weather(self, place: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
                areas = await self._get_areas(client)
                resolved = resolve_place(areas, place[:50])
                if not resolved:
                    return f"「{place}」がどこかわかりませんでした。市区町村名か都道府県名で聞き直してください。"
                office, class10, name = resolved
                resp = await client.get(FORECAST_URL.format(code=office))
                resp.raise_for_status()
                return f"{name}の予報（気象庁）\n" + format_forecast(resp.json(), class10)
        except Exception as e:
            log.warning("get_weather failed for %r: %s", place, e)
            return "天気予報を取得できませんでした。取得できなかったことを正直に伝えてください。"
