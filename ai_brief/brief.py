import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .api import NewsAPI
from .sources import HK, fetch


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as f:
        name = f.name
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        except BaseException:
            f.close()
            Path(name).unlink(missing_ok=True)
            raise
    os.replace(name, path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ranked_events(selection, articles):
    events, assigned = [], set()
    for event in selection.events:
        origins = []
        for origin in event.origins:
            members = []
            for index in origin.ids:
                if index not in assigned and 0 <= index < len(articles):
                    assigned.add(index)
                    members.append(index)
            if members:
                origins.append(members)
        if not origins:
            continue
        primary = set(event.primary_ids)
        candidates = [i for origin in origins for i in origin]
        candidates.sort(key=lambda i: i not in primary)
        # Mirrors may supply a readable alternative, but count only once.
        events.append({"candidates": [articles[i]["url"] for i in candidates],
                       "sources": [{"url": articles[group[0]]["url"],
                                    "title": articles[group[0]]["title"]} for group in origins],
                       "has_primary": any(i in primary for i in candidates)})
    return sorted(events, key=lambda event: (-len(event["sources"]), not event["has_primary"]))


def get_article(url, day, loader):
    try:
        return loader(url, day), False
    except (httpx.HTTPError, OSError, TimeoutError):
        print(f"原文暂时无法读取：{urlsplit(url).hostname}", flush=True)
        return None, True


def generate(day, root, *, api_factory=NewsAPI, loader=fetch):
    final = root / "editions" / f"{day}.json"
    checkpoint = root / "progress" / f"{day}.json"
    if final.exists():
        return read(final)
    state = read(checkpoint) if checkpoint.exists() else {"searches": {}, "summaries": {}, "usage": {}}

    def record(response, model):
        usage = state["usage"].setdefault(model, dict(requests=0, input_tokens=0, output_tokens=0, searches=0))
        usage["requests"] += 1
        if response.usage:
            usage["input_tokens"] += response.usage.input_tokens
            usage["output_tokens"] += response.usage.output_tokens
        usage["searches"] += sum(item.type == "web_search_call" and
                                 getattr(item.action, "type", None) == "search" for item in response.output)
        save(checkpoint, state)

    api = api_factory(record)
    cache = {}
    if "events" not in state:
        for lang in ("中文", "英文"):
            if lang not in state["searches"]:
                state["searches"][lang] = api.discover(day, lang)
                save(checkpoint, state)
        urls = list(dict.fromkeys(u for group in state["searches"].values() for u in group))
        with ThreadPoolExecutor(max_workers=6) as pool:
            items = list(pool.map(lambda u: get_article(u, day, loader), urls))
        for article, _ in items:
            if article:
                cache[article["url"]] = article
        if not cache and any(failed for _, failed in items):
            raise RuntimeError("原文读取有暂时性错误，未能核实任何文章，请补跑。")
        articles = list(cache.values())
        state["events"] = ranked_events(api.select(day, articles), articles) if articles else []
        save(checkpoint, state)
    stories = []
    for event in state["events"]:
        for url in event["candidates"]:
            if url not in state["summaries"]:
                article = cache.get(url)
                if not article:
                    article, temporary_failure = get_article(url, day, loader)
                    if temporary_failure:
                        # Allow another source for this event, retry later if none can be read.
                        continue
                item = api.summarize(day, article) if article else None
                if item:
                    item["source"] = {"url": article["url"], "title": article["title"]}
                state["summaries"][url] = item
                save(checkpoint, state)
            item = state["summaries"][url]
            if item:
                stories.append({**item, "sources": event["sources"], "count": len(event["sources"])})
                break
        else:
            if any(url not in state["summaries"] for url in event["candidates"]):
                raise RuntimeError("入选事件的原文暂时无法读取，请补跑。")
        if len(stories) == 8:
            break
    edition = {"date": day.isoformat(), "updated": datetime.now(HK).isoformat(timespec="minutes"),
               "stories": stories, "usage": state["usage"]}
    save(final, edition)
    checkpoint.unlink(missing_ok=True)
    return edition
