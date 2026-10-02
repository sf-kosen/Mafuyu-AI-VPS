import asyncio
import unittest
from unittest.mock import AsyncMock

from mafuyu.context import find_chinese
from mafuyu.research import Research
from mafuyu.search import WebSearch
from mafuyu.weather import format_forecast, resolve_place
from mafuyu.web import BlockedURL, check_public_url

AREAS = {
    "offices": {
        "130000": {"name": "東京都"},
        "140000": {"name": "神奈川県"},
        "260000": {"name": "京都府"},
        "014030": {"name": "十勝地方"},
    },
    "class10s": {
        "130010": {"name": "東京地方", "parent": "130000"},
        "140010": {"name": "東部", "parent": "140000"},
        "140020": {"name": "西部", "parent": "140000"},
        "260010": {"name": "南部", "parent": "260000"},
    },
    "class15s": {
        "130011": {"parent": "130010"},
        "140011": {"parent": "140010"},
        "140021": {"parent": "140020"},
        "260011": {"parent": "260010"},
    },
    "class20s": {
        "1310100": {"name": "千代田区", "parent": "130011"},
        "1420500": {"name": "藤沢市", "parent": "140011"},
        "1420600": {"name": "小田原市", "parent": "140021"},
        "2610000": {"name": "京都市", "parent": "260011"},
    },
}


class ResolvePlaceTest(unittest.TestCase):
    def test_city(self):
        self.assertEqual(resolve_place(AREAS, "藤沢"), ("140000", "140010", "藤沢市"))
        self.assertEqual(resolve_place(AREAS, "神奈川県小田原市の天気"), ("140000", "140020", "小田原市"))

    def test_prefecture_names_do_not_collide(self):
        self.assertEqual(resolve_place(AREAS, "東京都")[0], "130000")
        self.assertEqual(resolve_place(AREAS, "東京")[0], "130000")
        self.assertEqual(resolve_place(AREAS, "京都府")[0], "260000")
        self.assertEqual(resolve_place(AREAS, "京都")[0], "260000")

    def test_alias_and_region_and_unknown(self):
        self.assertEqual(resolve_place(AREAS, "北海道")[0], "016000")
        self.assertEqual(resolve_place(AREAS, "十勝")[0], "014030")
        self.assertIsNone(resolve_place(AREAS, "アトランティス"))


class FormatForecastTest(unittest.TestCase):
    def test_picks_sub_area(self):
        data = [{
            "publishingOffice": "横浜地方気象台",
            "reportDatetime": "2026-10-01T11:00:00+09:00",
            "timeSeries": [
                {"timeDefines": ["2026-10-01T11:00:00+09:00", "2026-10-02T00:00:00+09:00"],
                 "areas": [
                     {"area": {"name": "東部", "code": "140010"}, "weathers": ["くもり　時々　晴れ", "晴れ"]},
                     {"area": {"name": "西部", "code": "140020"}, "weathers": ["雨", "雨"]},
                 ]},
                {"timeDefines": ["2026-10-01T12:00:00+09:00"],
                 "areas": [{"area": {"name": "東部", "code": "140010"}, "pops": ["20"]},
                           {"area": {"name": "西部", "code": "140020"}, "pops": ["80"]}]},
                {"timeDefines": ["2026-10-01T09:00:00+09:00"],
                 "areas": [{"area": {"name": "横浜"}, "temps": ["26"]}]},
            ],
        }]
        text = format_forecast(data, "140010")
        self.assertIn("【東部】", text)
        self.assertIn("10/1(木) くもり時々晴れ", text)
        self.assertIn("10/1(木)12時〜 20%", text)
        self.assertNotIn("西部", text)
        self.assertIn("横浜: 10/1(木)最高26℃", text)


class CheckPublicUrlTest(unittest.TestCase):
    def check(self, url):
        asyncio.run(check_public_url(url))

    def test_blocks_non_public(self):
        for url in [
            "http://127.0.0.1/",
            "http://localhost:8080/",
            "http://[::1]/",
            "http://10.0.0.1/",
            "http://172.16.0.2/",  # the WARP tunnel address
            "http://169.254.169.254/latest/meta-data/",
            "http://[::ffff:127.0.0.1]/",
            "file:///etc/passwd",
            "ftp://example.com/",
            "http://user:pass@example.com/",
        ]:
            with self.subTest(url=url), self.assertRaises(BlockedURL):
                self.check(url)


class WebSearchTest(unittest.TestCase):
    def test_parse_serper(self):
        data = {
            "answerBox": {"title": "Python", "answer": "3.14", "link": "https://python.org"},
            "organic": [{"title": "t1", "link": "https://a.example", "snippet": "s1", "date": "2日前"}],
        }
        rows = WebSearch.parse_serper(data, "general")
        self.assertEqual(rows[0], {"title": "Python", "url": "https://python.org", "text": "3.14"})
        self.assertEqual(rows[1], {"title": "t1", "url": "https://a.example", "text": "2日前 s1"})

    def test_falls_back_in_order(self):
        search = WebSearch("http://127.0.0.1:8888", "serper-key")
        search._searxng = AsyncMock(side_effect=RuntimeError("no engine answered"))
        search._serper = AsyncMock(return_value=[{"title": "g", "url": "https://g.example", "text": "hit"}])
        search._ddg = AsyncMock()
        self.assertEqual(asyncio.run(search.results("q"))[0]["title"], "g")
        search._ddg.assert_not_called()

    def test_searxng_before_serper(self):
        search = WebSearch("http://127.0.0.1:8888/", "serper-key")
        search._searxng = AsyncMock(return_value=[{"title": "s", "url": "https://s.example", "text": "x"}])
        search._serper = AsyncMock()
        self.assertEqual(asyncio.run(search.results("q"))[0]["title"], "s")
        search._serper.assert_not_called()

    def test_searxng_down_falls_through(self):
        search = WebSearch("http://127.0.0.1:8888", None)
        search._searxng = AsyncMock(side_effect=RuntimeError("no engine answered"))
        search._ddg = AsyncMock(return_value=[{"title": "d", "url": "https://d.example", "text": "y"}])
        self.assertEqual(asyncio.run(search.results("q"))[0]["title"], "d")

    def test_ddg_when_no_keys(self):
        search = WebSearch(None, None)
        search._ddg = AsyncMock(return_value=[])
        self.assertEqual(asyncio.run(search.results("q")), [])
        search._ddg.assert_awaited_once()


class FindChineseTest(unittest.TestCase):
    def test_detects(self):
        self.assertEqual(find_chinese("模型のほうはどう？"), ["模型"])
        self.assertIn("这", find_chinese("这个很好"))

    def test_japanese_passes(self):
        for text in ["没頭してた", "データベースの情報を見る", "開発するのが楽しいね", "東京は晴れ"]:
            with self.subTest(text=text):
                self.assertEqual(find_chinese(text), [])


class CleanUrlTest(unittest.TestCase):
    def test_strips_tracking(self):
        from mafuyu.search import clean_url
        self.assertEqual(clean_url("https://tabelog.com/a/?msockid=abc"), "https://tabelog.com/a/")
        self.assertEqual(clean_url("https://x.jp/p?id=3&utm_source=t"), "https://x.jp/p?id=3")
        self.assertEqual(clean_url("https://x.jp/p"), "https://x.jp/p")


class ExtractTest(unittest.TestCase):
    def test_listing_page_gets_headings(self):
        from mafuyu.web import _extract
        html = ("<html><body><h2>藤沢駅の海鮮のお店</h2><h3>殻YABURI 藤沢店</h3>"
                "<h3>喜びの里</h3><h3>喜びの里</h3></body></html>").encode()
        text = _extract(html, "text/html", None)
        self.assertIn("- 殻YABURI 藤沢店", text)
        self.assertEqual(text.split("【ページ内の見出し】")[1].count("喜びの里"), 1)

    def test_shift_jis_meta(self):
        from mafuyu.web import _extract
        html = '<html><head><meta charset="shift_jis"></head><body><h2>初心者におすすめ</h2></body></html>'
        self.assertIn("初心者におすすめ", _extract(html.encode("cp932"), "text/html", None))


class ResearchTest(unittest.TestCase):
    def test_terms_skip_particles(self):
        from mafuyu.research import query_terms
        terms = query_terms("藤沢の海鮮")
        self.assertIn("海鮮", terms)
        self.assertIn("藤沢", terms)
        self.assertFalse(any(t == "のお" for t in query_terms("お店のおすすめ")))

    def test_excerpt_keeps_title_with_its_paragraph(self):
        from mafuyu.research import pick_excerpt, query_terms
        text = ("ロマンシング サガ2 リベンジオブザセブン\n"
                "七英雄と戦う王道RPGで、皇帝を代替わりさせながら進める独特のシステムが特徴です。\n"
                "カルドセプト ビギンズ\n"
                "Switch 2 Editionではおすそわけ通信に対応し、カードゲームの駆け引きを最大4人で楽しめるおすすめの一本です。")
        out = pick_excerpt(text, query_terms("Switch2 おすすめ 4人"))
        self.assertIn("カルドセプト ビギンズ\nSwitch 2 Editionでは", out)

    def test_excerpt_marks_skipped_lines(self):
        from mafuyu.research import pick_excerpt, query_terms
        text = ("藤沢の海鮮丼が人気のお店について、地元の人の口コミをまとめました。ここから紹介します。\n"
                + "関係のない長い段落がここに入ります。会社の沿革やアクセスの説明などが続きます。\n" * 3
                + "藤沢駅の北口にある海鮮食堂は、新鮮な海鮮丼が手頃な値段で食べられると評判です。")
        out = pick_excerpt(text, query_terms("藤沢 海鮮"))
        self.assertIn("\n…\n", out)

    def test_merge_interleaves_and_dedupes(self):
        from mafuyu.research import merge_results
        a = [{"url": "https://a/1"}, {"url": "https://a/2"}]
        b = [{"url": "https://a/1?msockid=x"}, {"url": "https://b/2"}]
        self.assertEqual([r["url"] for r in merge_results([a, b])],
                         ["https://a/1", "https://a/2", "https://b/2"])

    def test_merge_drops_chinese_sites(self):
        from mafuyu.research import merge_results
        rows = [{"url": u} for u in ("https://zhuanlan.zhihu.com/p/1", "https://zh.wikipedia.org/x",
                                     "https://example.cn/", "https://ja.wikipedia.org/wiki/y")]
        self.assertEqual([r["url"] for r in merge_results([rows])], ["https://ja.wikipedia.org/wiki/y"])

    def test_excerpt_prefers_relevant_and_skips_nav_headings(self):
        from mafuyu.research import pick_excerpt, query_terms
        text = ("会社概要とアクセスのご案内です。ここは関係のない段落になります。\n"
                "藤沢駅の海鮮居酒屋なら、しらす丼が人気の店が多いです。\n"
                "【ページ内の見出し】\n- エリアから探す\n- 予算\n- 藤沢駅の海鮮のお店\n- 喜びの里\n- 殻YABURI 藤沢店")
        out = pick_excerpt(text, query_terms("藤沢 海鮮 おすすめ"))
        self.assertIn("見出し: 藤沢駅の海鮮のお店 / 喜びの里 / 殻YABURI 藤沢店", out)
        self.assertIn("しらす丼", out)
        self.assertNotIn("会社概要", out)
        self.assertNotIn("エリアから探す", out)

    def test_end_to_end_with_snippet_fallback(self):
        search = WebSearch(None, None)
        search.results = AsyncMock(side_effect=[
            [{"title": "A", "url": "https://a.example/", "text": "snippet A"}],
            [{"title": "B", "url": "https://b.example/", "text": "snippet B"}],
        ])
        pages = {"https://a.example/": "藤沢の海鮮のおすすめは喜びの里です。地元の人にも人気があります。" * 8,
                 "https://b.example/": ""}
        rs = Research(search)
        rs._read = AsyncMock(side_effect=lambda url: pages[url])
        out = asyncio.run(rs.web_search("藤沢 海鮮", ["藤沢 海鮮 ランキング"]))
        self.assertIn("【1】A（a.example）", out)
        self.assertIn("喜びの里", out)
        self.assertIn("（本文は読めなかった。検索結果の抜粋）snippet B", out)

    def test_all_searches_failed(self):
        search = WebSearch(None, None)
        search.results = AsyncMock(return_value=None)
        out = asyncio.run(Research(search).web_search("q"))
        self.assertIn("検索に失敗しました", out)

    def test_single_query_and_duplicate_phrasings(self):
        search = WebSearch(None, None)
        search.results = AsyncMock(return_value=[])
        out = asyncio.run(Research(search).web_search(" q ", ["q", ""]))
        self.assertEqual(out, "検索結果はありませんでした。")
        search.results.assert_awaited_once_with("q", "general", None)


if __name__ == "__main__":
    unittest.main()
