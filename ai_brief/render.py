from datetime import date, datetime
from pathlib import Path
from shutil import copyfile
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .brief import read
from .sources import clean_url

ASSETS = Path(__file__).with_name("templates")


def render(root, output):
    files = sorted((root / "editions").glob("????-??-??.json"), reverse=True)
    if not files:
        raise RuntimeError("尚无已完成的日报。")
    env = Environment(loader=FileSystemLoader(ASSETS), autoescape=select_autoescape(["html"]))
    env.filters["safe_url"] = lambda url: clean_url(url) or "#"
    env.filters["host"] = lambda url: urlsplit(url).hostname or "来源"
    env.filters["clock"] = lambda value: datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    env.filters["weekday"] = lambda value: "星期" + "一二三四五六日"[date.fromisoformat(value).weekday()]
    output.mkdir(parents=True, exist_ok=True)
    copyfile(ASSETS / "brief.css", output / "brief.css")
    dates = [f.stem for f in files]
    for i, path in enumerate(files):
        edition = read(path)
        folder = output / "issues" / path.stem
        folder.mkdir(parents=True, exist_ok=True)
        template = env.get_template("brief.html")
        (folder / "index.html").write_text(template.render(issue=edition, base="../../"), encoding="utf-8")
        if i == 0:
            (output / "index.html").write_text(template.render(issue=edition, base="./"), encoding="utf-8")
    (output / "archive.html").write_text(env.get_template("archive.html").render(dates=dates, base="./"),
                                         encoding="utf-8")
