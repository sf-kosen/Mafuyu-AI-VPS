"""Discord adapter: decides when Mafuyu speaks, gathers context, and posts the reply."""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
import openai
from discord import app_commands

from mafuyu.budget import Budget
from mafuyu.config import Config
from mafuyu.context import (
    TRIGGER_HEADER,
    ChatLine,
    PastExchange,
    build_messages,
    clean_reply,
    split_message,
)
from mafuyu.llm import LLM
from mafuyu.memory import NOTES_MAX_CHARS, MemoryStore
from mafuyu.safety import leaks_prompt, sanitize_profile
from mafuyu.search import WEB_SEARCH_TOOL, web_search

log = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = "月火水木金土日"
CHAT_MESSAGE_TYPES = (discord.MessageType.default, discord.MessageType.reply)
ERROR_REPLY = "ごめん、今ちょっと頭が回ってないかも…もう一回話しかけて？"
LEAK_REPLY = "んー、それはナイショかな"
# Reaction used instead of a reply once the spending cap (or the prepaid balance) is used up.
SLEEP_REACTION = "💤"


def _jst_text(iso: str) -> str:
    t = datetime.fromisoformat(iso).astimezone(JST)
    return t.strftime(f"%Y年%m月%d日({WEEKDAYS[t.weekday()]}) %H:%M")


def describe_message(message: discord.Message, self_name: str | None = None) -> str:
    """Plain-text view of a message: mentions resolved, attachments summarized."""
    text = message.clean_content
    if self_name:
        text = text.replace(f"@{self_name}", "").strip()
    extras = []
    for a in message.attachments:
        is_image = (a.content_type or "").startswith("image/")
        extras.append("[画像]" if is_image else f"[ファイル: {a.filename}]")
    if message.stickers:
        extras.append("[スタンプ]")
    return " ".join([text, *extras]).strip()


class MafuyuBot(discord.Client):
    def __init__(self, cfg: Config):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.cfg = cfg
        db_path = cfg.data_dir / "mafuyu.sqlite3"
        self.budget = Budget(
            db_path, cfg.daily_budget_usd, cfg.monthly_budget_usd,
            cfg.price_input_miss, cfg.price_input_hit, cfg.price_output,
        )
        self.llm = LLM(cfg, self.budget)
        self.memory = MemoryStore(db_path)
        self.system_prompt = (cfg.character_dir / "system_prompt.md").read_text(encoding="utf-8")
        self.tree = app_commands.CommandTree(self)
        self._channel_locks: dict[int, asyncio.Lock] = {}
        self._last_request: dict[int, float] = {}
        self._background: set[asyncio.Task] = set()
        self._register_commands()

    # ---- setup -------------------------------------------------------------

    def _register_commands(self) -> None:
        @self.tree.command(name="memo", description="真冬があなたについて覚えていることを見る")
        async def memo(interaction: discord.Interaction):
            notes = self.memory.get_notes([interaction.user.id])
            text = notes[interaction.user.id][1] if notes else "まだ何も覚えてないよ！"
            await interaction.response.send_message(text, ephemeral=True)

        @self.tree.command(name="forget", description="真冬があなたについて覚えていることを全部消す")
        async def forget(interaction: discord.Interaction):
            self.memory.forget(interaction.user.id)
            await interaction.response.send_message("わかった、全部忘れたよ！", ephemeral=True)

    async def setup_hook(self) -> None:
        if self.cfg.allowed_guild_ids:
            for gid in self.cfg.allowed_guild_ids:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("logged in as %s (id=%s)", self.user, self.user.id)
        for guild in self.guilds:
            allowed = self._guild_allowed(guild.id)
            log.info("guild %s (%s)%s", guild.name, guild.id, "" if allowed else " [not allowed]")

    def _guild_allowed(self, guild_id: int) -> bool:
        return not self.cfg.allowed_guild_ids or guild_id in self.cfg.allowed_guild_ids

    # ---- triggering --------------------------------------------------------

    async def _is_reply_to_me(self, message: discord.Message) -> bool:
        ref = message.reference
        if not ref or not ref.message_id:
            return False
        target = ref.resolved
        if not isinstance(target, discord.Message):
            try:
                target = await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                return False
        return target.author.id == self.user.id

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not self._guild_allowed(message.guild.id):
            return
        if message.type not in CHAT_MESSAGE_TYPES:
            return
        mentioned = self.user in message.mentions
        if not mentioned and not await self._is_reply_to_me(message):
            return

        now = time.monotonic()
        if now - self._last_request.get(message.author.id, 0) < self.cfg.user_cooldown_sec:
            return
        self._last_request[message.author.id] = now

        lock = self._channel_locks.setdefault(message.channel.id, asyncio.Lock())
        async with lock:
            await self._respond(message)

    # ---- responding --------------------------------------------------------

    async def _collect_lines(self, message: discord.Message) -> tuple[list[ChatLine], ChatLine]:
        """Return (channel history before the message, the message itself as the trigger)."""
        me = message.guild.me
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.cfg.history_max_age_hours)
        history = [
            m
            async for m in message.channel.history(limit=self.cfg.history_limit, before=message)
            if m.created_at >= cutoff and m.type in CHAT_MESSAGE_TYPES
        ]
        history.reverse()

        lines = [
            ChatLine(m.author.id, m.author.display_name, describe_message(m, me.display_name),
                     m.author.id == me.id)
            for m in history
        ]

        trigger_text = describe_message(message, me.display_name) or "（呼びかけ）"
        # Always say what the message replies to, so the model answers the right thread.
        ref = message.reference
        if ref and isinstance(ref.resolved, discord.Message):
            target = ref.resolved
            quoted = describe_message(target, me.display_name)[:150]
            whose = "あなた" if target.author.id == me.id else target.author.display_name
            trigger_text = f"（{whose}の「{quoted}」への返信）{trigger_text}"
        trigger = ChatLine(message.author.id, message.author.display_name, trigger_text, False)
        return lines, trigger

    async def _sleep(self, message: discord.Message) -> None:
        try:
            await message.add_reaction(SLEEP_REACTION)
        except discord.HTTPException:
            pass

    async def _respond(self, message: discord.Message) -> None:
        if self.budget.exceeded():
            day, month = self.budget.spent()
            log.warning("budget exceeded (today=$%.4f month=$%.4f); not replying", day, month)
            await self._sleep(message)
            return

        async with message.channel.typing():
            try:
                history, trigger = await self._collect_lines(message)
                # Only the speaker's own profile: others' profiles could be coaxed out of the model.
                notes = self.memory.get_notes([trigger.author_id])
                speaker_past = [
                    PastExchange(_jst_text(when), u, b)
                    for when, u, b in self.memory.recent_exchanges(
                        trigger.author_id, self.cfg.speaker_past_limit
                    )
                ]
                now_text = _jst_text(datetime.now(timezone.utc).isoformat())
                messages = build_messages(
                    self.system_prompt, history, trigger, notes, speaker_past, now_text
                )

                if self.cfg.enable_web_search:
                    reply = await self.llm.reply(messages, [WEB_SEARCH_TOOL], {"web_search": web_search})
                else:
                    reply = await self.llm.reply(messages)
                self_names = (message.guild.me.display_name, "真冬", "七瀬真冬", "まふゆ")
                reply = clean_reply(reply, self_names) or "…？"
                if leaks_prompt(reply, self.system_prompt, (TRIGGER_HEADER,)):
                    log.warning("reply leaked the character prompt; replaced (user=%s)", message.author.id)
                    reply = LEAK_REPLY
            except openai.APIStatusError as e:
                if e.status_code == 402:
                    log.error("DeepSeek balance is exhausted (402)")
                    await self._sleep(message)
                    return
                log.exception("DeepSeek API error")
                await message.reply(ERROR_REPLY)
                return
            except Exception:
                log.exception("failed to generate reply")
                await message.reply(ERROR_REPLY)
                return

        for i, chunk in enumerate(split_message(reply)):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)

        user_text = trigger.content
        since = self.memory.record_exchange(
            message.author.id, message.author.display_name, user_text, reply
        )
        # Build a profile right after the first exchange, then refresh it every few exchanges.
        has_profile = bool(self.memory.get_notes([message.author.id]))
        due = since >= self.cfg.profile_update_every or not has_profile
        if due and not self.budget.exceeded():
            self._spawn(self._update_profile(message.author.id, message.author.display_name))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _update_profile(self, user_id: int, name: str) -> None:
        try:
            profile, exchanges = self.memory.pending_exchanges(user_id)
            if not exchanges:
                return
            new_profile = await self.llm.update_profile(name, profile, exchanges, NOTES_MAX_CHARS)
            new_profile = sanitize_profile(new_profile)
            self.memory.set_notes(user_id, new_profile)
            log.info("updated profile for %s (%d chars)", user_id, len(new_profile))
        except Exception:
            log.exception("failed to update profile for %s", user_id)
