import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError

from .brief import generate
from .render import render
from .sources import HK


def main():
    parser = argparse.ArgumentParser(description="生成香港时间上一完整自然日的 AI 资讯早报。")
    parser.add_argument("--date", type=date.fromisoformat, metavar="YYYY-MM-DD")
    parser.add_argument("--render-only", action="store_true", help="从已归档日报重建静态站，无需密钥")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="日报数据与 dist 输出目录")
    args = parser.parse_args()
    root = args.root.resolve()
    if not args.render_only:
        today = datetime.now(HK).date()
        day = args.date or today - timedelta(days=1)
        if day >= today:
            parser.error("请选择香港时间已结束的自然日。")
        if not (root / "editions" / f"{day}.json").exists():
            load_dotenv(root / ".env.local", override=False)
            if not os.environ.get("OPENAI_API_KEY"):
                parser.exit(1, "未配置 OPENAI_API_KEY，请为定时任务设置同名 Secret。\n")
        issue = generate(day, root)
        print(f"{day}：{len(issue['stories'])} 条新闻。用量：{issue['usage']}")
    render(root, root / "dist")


if __name__ == "__main__":
    try:
        main()
    except APIStatusError as error:
        print(f"OpenAI 请求失败，HTTP {error.status_code}，代码 {error.code}。本期已暂停。", file=sys.stderr)
        sys.exit(1)
