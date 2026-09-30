import logging

from mafuyu.bot import MafuyuBot
from mafuyu.config import load_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # discord.py and httpx are noisy at INFO.
    logging.getLogger("discord").setLevel(logging.WARNING)
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)

    cfg = load_config()
    MafuyuBot(cfg).run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
