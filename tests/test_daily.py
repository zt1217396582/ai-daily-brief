from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup

from ai_brief.api import Event, NewsAPI, Origin, Selection
from ai_brief.brief import generate, ranked_events
from ai_brief.render import render
from ai_brief.sources import clean_url, parse_article


DAY = date(2026, 11, 18)


def article(url, day):
    return {"url": url, "title": "测试稿", "published": str(day), "body": "示例正文" * 80}


class DailyTests(unittest.TestCase):
    def test_hong_kong_boundary(self):
        def html(stamp):
            return (f'<meta property="article:published_time" content="{stamp}">'
                    f'<article><h1>公告</h1><p>{"报道正文" * 60}</p></article>')
        self.assertIsNotNone(parse_article(html("2026-11-17T16:00:00Z"), "https://example.org", DAY))
        self.assertIsNone(parse_article(html("2026-11-18T16:00:00Z"), "https://example.org", DAY))
        self.assertIsNone(parse_article(html("2026-11-18"), "https://example.org", DAY))
        self.assertIsNone(parse_article(html("2026-11-18T12:00:00Z").replace("published_time", "modified_time"),
                                        "https://example.org", DAY))

    def test_syndication_and_primary_tie(self):
        articles = [article(f"https://example.org/{n}", DAY) for n in range(5)]
        choices = Selection(events=[
            Event(subject="甲", origins=[Origin(ids=[0])], primary_ids=[]),
            Event(subject="乙", origins=[Origin(ids=[1])], primary_ids=[1]),
            Event(subject="丙", origins=[Origin(ids=[2, 3]), Origin(ids=[4, 2, 10])], primary_ids=[3])])
        picked = ranked_events(choices, articles)
        self.assertEqual([len(e["sources"]) for e in picked], [2, 1, 1])
        self.assertEqual(picked[0]["candidates"][0], articles[3]["url"])
        self.assertTrue(picked[1]["has_primary"])

    def test_empty_issue_and_resume_search(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = Mock()
            api.discover.side_effect = [[], RuntimeError("quota")]
            with self.assertRaises(RuntimeError):
                generate(DAY, root, api_factory=lambda record: api)
            self.assertFalse((root / "editions" / f"{DAY}.json").exists())
            api.discover.reset_mock(side_effect=True)
            api.discover.return_value = []
            issue = generate(DAY, root, api_factory=lambda record: api)
            api.discover.assert_called_once_with(DAY, "英文")
            self.assertEqual(issue["stories"], [])
            render(root, root / "dist")
            self.assertIn("本期无入选资讯", (root / "dist/index.html").read_text(encoding="utf-8"))

    def test_summary_checkpoint_and_latest_archive(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            urls = ["https://example.org/a", "https://example.org/b"]
            api = Mock()
            api.discover.return_value = urls
            api.select.return_value = Selection(events=[
                Event(subject=str(i), origins=[Origin(ids=[i])], primary_ids=[]) for i in range(2)])
            story = {"title": "<示例>", "summary": "摘要", "impact": "对读者的影响"}
            api.summarize.side_effect = [story.copy(), RuntimeError("interruption")]
            with self.assertRaises(RuntimeError):
                generate(DAY, root, api_factory=lambda record: api, loader=article)
            api.summarize.reset_mock(side_effect=True)
            api.summarize.return_value = story.copy()
            issue = generate(DAY, root, api_factory=lambda record: api, loader=article)
            self.assertEqual(len(issue["stories"]), 2)
            api.summarize.assert_called_once()
            self.assertEqual(generate(DAY, root, api_factory=self.fail), issue)
            old_day = date(2026, 11, 17)
            api.discover.return_value = []
            generate(old_day, root, api_factory=lambda record: api, loader=article)
            render(root, root / "dist")
            for day in (old_day, DAY):
                self.assertTrue((root / "dist/issues" / str(day) / "index.html").exists())
            page = BeautifulSoup((root / "dist/index.html").read_text(encoding="utf-8"), "html.parser")
            self.assertEqual(len(page.select("article")), 2)
            self.assertEqual(page.select_one("article h2").text, "<示例>")
            self.assertIsNone(page.script)
            self.assertIsNotNone(page.select_one(f'a[href="./issues/{DAY}/"]'))

    def test_search_uses_observed_safe_urls(self):
        items = [
            {"type": "web_search_call", "status": "completed",
             "action": {"type": "search", "sources": None}},
            {"type": "message", "content": [{"annotations": [
                {"type": "url_citation", "url": "https://example.org/x?utm_source=news"},
                {"type": "url_citation", "url": "javascript:void(0)"}]}]}]
        api = NewsAPI.__new__(NewsAPI)
        api.call = Mock(return_value=SimpleNamespace(output=[Mock(model_dump=lambda d=d: d) for d in items]))
        self.assertEqual(api.discover(DAY, "中文"), ["https://example.org/x"])
        self.assertFalse(clean_url("https://name:secret@example.org"))
