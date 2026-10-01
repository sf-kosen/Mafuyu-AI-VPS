"""The set of tools the model may call, and their implementations."""

from mafuyu.llm import ToolImpl
from mafuyu.research import WEB_SEARCH_TOOL, Research
from mafuyu.search import WebSearch
from mafuyu.weather import GET_WEATHER_TOOL, WeatherClient
from mafuyu.web import READ_URL_TOOL, read_url


def build_tools(
    searxng_url: str | None, serper_api_key: str | None
) -> tuple[list[dict], dict[str, ToolImpl]]:
    research = Research(WebSearch(searxng_url, serper_api_key))
    weather = WeatherClient()
    specs = [WEB_SEARCH_TOOL, READ_URL_TOOL, GET_WEATHER_TOOL]
    impls: dict[str, ToolImpl] = {
        "web_search": research.web_search,
        "read_url": read_url,
        "get_weather": weather.get_weather,
    }
    return specs, impls
