"""读取公开网页，仅接受能在原文中验证的发布时间与正文。"""
import ipaddress
import json
import re
import socket
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

HK = ZoneInfo("Asia/Hong_Kong")
MAX_BYTES = 2_500_000
AGENT = "AI-Daily-Brief/1.0 (public article reader)"


def clean_url(url):
    try:
        p = urlsplit(url)
        if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
            return ""
        if p.port not in (None, 80, 443) or any(c.isspace() for c in url):
            return ""
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k not in ("fbclid", "gclid")]
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", urlencode(query), ""))
    except (TypeError, ValueError):
        return ""


def publication_time(soup):
    # Prefer explicit publication fields. Modification timestamps can refer to old news.
    values = []
    for tag in soup.select('meta[property="article:published_time"], meta[itemprop="datePublished"], time[itemprop="datePublished"]'):
        values.append(tag.get("content") or tag.get("datetime"))
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.get_text())
        except (ValueError, RecursionError):
            continue
        queue = data if isinstance(data, list) else [data]
        for node in queue:
            if not isinstance(node, dict):
                continue
            kinds = node.get("@type", "")
            if isinstance(kinds, str):
                kinds = [kinds]
            if isinstance(kinds, list) and any(k in ("Article", "NewsArticle", "BlogPosting", "TechArticle", "Report", "ScholarlyArticle", "ReportageNewsArticle") for k in kinds):
                values.append(node.get("datePublished"))
            for key in ("@graph", "mainEntity"):
                nested = node.get(key)
                if isinstance(nested, (list, dict)):
                    queue.extend(nested if isinstance(nested, list) else [nested])
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                return dt.astimezone(HK)
        except (ValueError, OverflowError):
            continue
    return None


def parse_article(html, url, day: date):
    soup = BeautifulSoup(html, "html.parser")
    published = publication_time(soup)
    if not published or published.date() != day:
        return None
    for tag in soup.select("script, style, nav, footer, aside, header nav, form, noscript"):
        tag.decompose()
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    if not root:
        return None
    paragraphs = [" ".join(tag.stripped_strings) for tag in root.select("p")]
    body = "\n".join(dict.fromkeys(p for p in paragraphs if len(p) >= 12))
    title_tag = root.select_one("h1") or soup.select_one("h1") or soup.title
    if not title_tag or len(body) < 180:
        return None
    return {"url": url, "title": title_tag.get_text(" ", strip=True)[:250],
            "published": published.isoformat(), "body": body[:18000]}


def fetch(url, day):
    # The reader is independent from the authenticated API client.
    with httpx.Client(timeout=12, headers={"User-Agent": AGENT}, trust_env=False) as reader:
        for _ in range(5):
            url = clean_url(url)
            if not url:
                return None
            host = urlsplit(url).hostname
            addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                return None
            # Pin the connection to the checked address, preserving the HTTP host and TLS SNI.
            ip = addresses[0][4][0]
            target = httpx.URL(url).copy_with(host=ip)
            with reader.stream("GET", target, headers={"Host": urlsplit(url).netloc},
                               extensions={"sni_hostname": host}) as response:
                if response.is_redirect and response.headers.get("location"):
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code in (408, 429) or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code != 200 or "html" not in response.headers.get("content-type", "").lower():
                    return None
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        return None
                return parse_article(bytes(content), url, day)
    return None
