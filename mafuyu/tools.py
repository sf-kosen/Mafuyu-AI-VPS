"""The set of tools the model may call, and their implementations."""

from mafuyu.deep import DEEP_SEARCH_TOOL, DeepSearch
from mafuyu.llm import ToolImpl
from mafuyu.search import WEB_SEARCH_TOOL, WebSearch
from mafuyu.weather import GET_WEATHER_TOOL, WeatherClient
from mafuyu.web import READ_URL_TOOL, read_url


def build_tools(
    searxng_url: str | None, serper_api_key: str | None
) -> tuple[list[dict], dict[str, ToolImpl]]:
    search = WebSearch(searxng_url, serper_api_key)
    deep = DeepSearch(search)
    weather = WeatherClient()
    specs = [WEB_SEARCH_TOOL, DEEP_SEARCH_TOOL, READ_URL_TOOL, GET_WEATHER_TOOL]
    impls: dict[str, ToolImpl] = {
        "web_search": search.search,
        "deep_search": deep.deep_search,
        "read_url": read_url,
        "get_weather": weather.get_weather,
    }
    return specs, impls
