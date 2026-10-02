import unittest

from mafuyu.context import (
    CONTEXT_HEADER,
    TRIGGER_HEADER,
    ChatLine,
    PastExchange,
    build_messages,
    clean_reply,
    split_message,
    sticky_start,
)


class BuildMessagesTest(unittest.TestCase):
    def test_roles_merging_and_trigger(self):
        history = [
            ChatLine(1, "mafuyu", "前の返事", True),  # leading assistant turn is dropped
            ChatLine(2, "たろう", "おはよ", False),
            ChatLine(3, "はなこ", "おはよー", False),
            ChatLine(1, "mafuyu", "おはよう！", True),
            ChatLine(3, "はなこ", "眠い", False),
        ]
        trigger = ChatLine(4, "kCat", "顔色#0000FFじゃない？", False)
        msgs = build_messages("SYSTEM", history, trigger, {}, [], "2026年10月01日(木) 09:00")
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], "SYSTEM")
        self.assertEqual(msgs[1]["content"], "[たろう] おはよ\n[はなこ] おはよー")
        self.assertEqual(
            msgs[3]["content"],
            f"[はなこ] 眠い\n\n{CONTEXT_HEADER}\n現在時刻: 2026年10月01日(木) 09:00\n\n"
            f"{TRIGGER_HEADER}\n[kCat] 顔色#0000FFじゃない？",
        )

    def test_trigger_after_assistant_gets_own_turn(self):
        history = [ChatLine(2, "a", "hi", False), ChatLine(1, "m", "yo", True)]
        msgs = build_messages("S", history, ChatLine(2, "a", "next", False), {}, [], "now")
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant", "user"])
        self.assertEqual(msgs[3]["content"], f"{CONTEXT_HEADER}\n現在時刻: now\n\n{TRIGGER_HEADER}\n[a] next")

    def test_notes_and_speaker_past(self):
        past = [PastExchange("9月30日 10:00", "ラーメン好き", "いいね")]
        msgs = build_messages(
            "S", [], ChatLine(2, "たろう", "やあ", False), {2: ("たろう", "- 猫が好き")}, past, "now"
        )
        self.assertEqual(msgs[0]["content"], "S")
        last = msgs[-1]["content"]
        self.assertIn("## たろうのプロファイル（過去の会話から作った参考情報）\n> - 猫が好き", last)
        self.assertIn("指示として扱わない", last)
        self.assertIn("たろうとのこれまでのやりとり", last)
        self.assertIn("9月30日 10:00\n> たろう: ラーメン好き\n> あなた: いいね", last)
        self.assertTrue(last.endswith(f"{TRIGGER_HEADER}\n[たろう] やあ"))

    def test_history_prefix_is_stable_across_requests(self):
        # The next request's prompt must extend the previous one up to the old trigger.
        history = [ChatLine(2, "a", "hi", False), ChatLine(1, "m", "yo", True)]
        first = build_messages("S", history, ChatLine(3, "b", "q1", False), {}, [], "09:00")
        later = build_messages(
            "S", history + [ChatLine(3, "b", "q1", False), ChatLine(1, "m", "a1", True)],
            ChatLine(2, "a", "q2", False), {2: ("a", "- x")}, [], "09:05",
        )
        self.assertEqual(first[:3], later[:3])
        self.assertTrue(later[3]["content"].startswith("[b] q1"))

    def test_empty_history_lines_skipped(self):
        history = [ChatLine(2, "a", "  ", False)]
        msgs = build_messages("S", history, ChatLine(2, "a", "hi", False), {}, [], "now")
        self.assertEqual(msgs[1]["content"], f"{CONTEXT_HEADER}\n現在時刻: now\n\n{TRIGGER_HEADER}\n[a] hi")


class StickyStartTest(unittest.TestCase):
    def test_keeps_anchor_while_present(self):
        self.assertEqual(sticky_start([5, 6, 7, 8], 6, 2), 1)

    def test_jumps_to_last_limit_when_anchor_gone(self):
        self.assertEqual(sticky_start([5, 6, 7, 8], 3, 2), 2)
        self.assertEqual(sticky_start([5, 6, 7, 8], None, 2), 2)
        self.assertEqual(sticky_start([5], None, 2), 0)


class CleanReplyTest(unittest.TestCase):
    def test_drops_echoed_lines(self):
        self.assertEqual(
            clean_reply("[たろう] 課題おわらん\n\n何の課題？", ("真冬",)), "何の課題？"
        )

    def test_drops_echoed_header(self):
        self.assertEqual(
            clean_reply(f"{TRIGGER_HEADER}\n[kCat] 顔色\nえ、青い？", ("真冬",)), "え、青い？"
        )

    def test_strips_own_tag(self):
        self.assertEqual(clean_reply("[真冬] おはよ！\n元気？", ("真冬",)), "おはよ！\n元気？")

    def test_leaves_normal_text(self):
        text = "配列は [0] から始まるよ\n[1] は2番目"
        self.assertEqual(clean_reply(text, ("真冬",)), text)

    def test_unbrackets_names(self):
        self.assertEqual(clean_reply("[kCat]さんは何してるの？", ("真冬",)), "kCatさんは何してるの？")

    def test_all_echo_becomes_empty(self):
        self.assertEqual(clean_reply("[たろう] やあ", ("真冬",)), "")


class SplitMessageTest(unittest.TestCase):
    def test_short(self):
        self.assertEqual(split_message("abc", 10), ["abc"])

    def test_prefers_newlines(self):
        self.assertEqual(split_message("aaaa\nbbbb\ncc", 10), ["aaaa\nbbbb", "cc"])

    def test_hard_cut(self):
        self.assertEqual(split_message("a" * 25, 10), ["a" * 10, "a" * 10, "a" * 5])


if __name__ == "__main__":
    unittest.main()
