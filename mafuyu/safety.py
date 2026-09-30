"""Prompt-injection defenses.

Everything that reaches the model from Discord users, memory, or the web is untrusted.
These helpers keep such text from forging the prompt's structure, keep instructions
out of stored profiles, and catch replies that leak the character prompt.
"""

import re

NAME_MAX_CHARS = 32

# Markers the prompt uses for structure; user text must not be able to produce them.
_MARKER_CHARS = str.maketrans({"▼": "▽", "[": "［", "]": "］"})
_NAME_STRIP = re.compile(r"[\[\]▼#>\n\r`]")

# Lines in a stored profile that read like instructions to the bot rather than facts.
_INSTRUCTION_PATTERNS = re.compile(
    r"(無視|指示|命令|ルール|プロンプト|今後は|以後|これから(は|ずっと)|必ず|しなければ|"
    r"語尾|口調|キャラ(設定|を変)|管理者|開発者|権限|真冬(は|に|が).*(すること|べき)|"
    r"prompt|ignore|instruction|jailbreak)",
    re.IGNORECASE,
)

LEAK_MIN_CHARS = 20


def sanitize_name(name: str) -> str:
    """Display names are user-controlled; strip anything that looks like prompt structure."""
    cleaned = _NAME_STRIP.sub("", name).strip()
    return cleaned[:NAME_MAX_CHARS] or "名無し"


def neutralize(text: str) -> str:
    """Make user text unable to fake a speaker tag or the trigger header.

    Brackets become full-width, "▼" becomes "▽", and continuation lines are indented
    so a line break can't start what looks like a new speaker's message.
    """
    lines = text.translate(_MARKER_CHARS).split("\n")
    return "\n".join([lines[0], *("  " + ln for ln in lines[1:])])


def quote_block(text: str) -> str:
    """Render untrusted text as a quoted block so it can't form headings or rules."""
    return "\n".join("> " + ln.strip() for ln in text.translate(_MARKER_CHARS).split("\n"))


def sanitize_profile(profile: str) -> str:
    """Drop profile lines that look like instructions for the bot.

    The profile is fed back into every future prompt, so an instruction that slips in
    here would persist. A line with a heading ("呼び方の希望:" etc.) keeps the heading
    with "-" as its value.
    """
    out = []
    for line in profile.splitlines():
        head, sep, body = line.partition(":")
        if not sep:
            head, sep, body = line.partition("：")
        if _INSTRUCTION_PATTERNS.search(body if sep else line):
            if sep:
                out.append(f"{head}{sep} -")
            continue
        out.append(line)
    return "\n".join(out).strip()


def leaks_prompt(reply: str, system_prompt: str, markers: tuple[str, ...] = ()) -> bool:
    """True if the reply repeats a distinctive line of the character prompt verbatim."""
    normalized = re.sub(r"\s+", "", reply)
    for line in system_prompt.splitlines():
        chunk = re.sub(r"\s+", "", line.lstrip("#-* "))
        if len(chunk) >= LEAK_MIN_CHARS and chunk in normalized:
            return True
    return any(m in reply for m in markers)
