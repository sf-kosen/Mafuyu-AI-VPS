import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _int_set(value: str) -> frozenset[int]:
    return frozenset(int(v) for v in value.replace(" ", "").split(",") if v)


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    discord_token: str
    deepseek_api_key: str
    deepseek_base_url: str
    model: str
    temperature: float
    max_output_tokens: int
    history_limit: int
    history_max_age_hours: float
    user_cooldown_sec: float
    allowed_guild_ids: frozenset[int]
    enable_web_search: bool
    tavily_api_key: str | None
    serper_api_key: str | None
    searxng_url: str | None
    profile_update_every: int
    thinking: bool
    thinking_max_tokens: int
    speaker_past_limit: int
    daily_budget_usd: float
    monthly_budget_usd: float
    price_input_miss: float
    price_input_hit: float
    price_output: float
    data_dir: Path
    character_dir: Path


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")

    missing = [k for k in ("DISCORD_TOKEN", "DEEPSEEK_API_KEY") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"環境変数が足りません: {', '.join(missing)}（.env を確認してください）")

    return Config(
        discord_token=os.environ["DISCORD_TOKEN"],
        deepseek_api_key=os.environ["DEEPSEEK_API_KEY"],
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        temperature=float(os.getenv("TEMPERATURE", "1.1")),
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "600")),
        history_limit=int(os.getenv("HISTORY_LIMIT", "20")),
        history_max_age_hours=float(os.getenv("HISTORY_MAX_AGE_HOURS", "12")),
        user_cooldown_sec=float(os.getenv("USER_COOLDOWN_SEC", "3")),
        allowed_guild_ids=_int_set(os.getenv("ALLOWED_GUILD_IDS", "")),
        enable_web_search=_bool(os.getenv("ENABLE_WEB_SEARCH", "1")),
        tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
        serper_api_key=os.getenv("SERPER_API_KEY") or None,
        searxng_url=os.getenv("SEARXNG_URL") or None,
        profile_update_every=int(os.getenv("PROFILE_UPDATE_EVERY", "3")),
        thinking=_bool(os.getenv("THINKING", "0")),
        thinking_max_tokens=int(os.getenv("THINKING_MAX_TOKENS", "3000")),
        speaker_past_limit=int(os.getenv("SPEAKER_PAST_LIMIT", "3")),
        daily_budget_usd=float(os.getenv("DAILY_BUDGET_USD", "0.1")),
        monthly_budget_usd=float(os.getenv("MONTHLY_BUDGET_USD", "2")),
        # USD per 1M tokens, peak-hour rates for deepseek-flash (2026-10)
        price_input_miss=float(os.getenv("PRICE_INPUT_MISS", "0.3")),
        price_input_hit=float(os.getenv("PRICE_INPUT_HIT", "0.006")),
        price_output=float(os.getenv("PRICE_OUTPUT", "1.2")),
        data_dir=Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))),
        character_dir=Path(os.getenv("CHARACTER_DIR", str(BASE_DIR / "character"))),
    )
