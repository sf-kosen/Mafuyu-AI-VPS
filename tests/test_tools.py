import asyncio
import unittest

from mafuyu.context import find_chinese
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


class FindChineseTest(unittest.TestCase):
    def test_detects(self):
        self.assertEqual(find_chinese("模型のほうはどう？"), ["模型"])
        self.assertIn("这", find_chinese("这个很好"))

    def test_japanese_passes(self):
        for text in ["没頭してた", "データベースの情報を見る", "開発するのが楽しいね", "東京は晴れ"]:
            with self.subTest(text=text):
                self.assertEqual(find_chinese(text), [])


if __name__ == "__main__":
    unittest.main()
