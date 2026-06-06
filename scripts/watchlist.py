#!/usr/bin/env python3
"""
watchlist.py
监控 watchlist.json 里的创作者，拉取最新视频，按点赞排名输出。

用法：
  python3 watchlist.py                          # 所有创作者，拉最近 20 条，展示 Top 5
  python3 watchlist.py --limit 30               # 每人拉最近 30 条
  python3 watchlist.py --top 10                 # 每人展示 Top 10
  python3 watchlist.py --name 编导李让          # 只查某一位
  python3 watchlist.py --category AI短片        # 只查某个分类
  python3 watchlist.py --list-categories        # 列出所有分类

  添加创作者：
  python3 watchlist.py --add --name "齐马蓝" --sec-uid <sec_uid> --category "爽文·反道德绑架" [--note "备注"]

注意：抖音 user-videos 只返回点赞数，无收藏/分享/评论。
      视频按发布时间倒序（index=1 为最新），--limit 控制拉多少条。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(TOOLS_DIR, "..", "data", "watchlist.json")


def load_watchlist() -> list[dict]:
    with open(WATCHLIST_FILE) as f:
        return json.load(f)["creators"]


def save_watchlist(creators: list[dict]):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump({"creators": creators}, f, ensure_ascii=False, indent=2)


def fetch_user_videos(sec_uid: str, limit: int) -> list[dict]:
    result = subprocess.run(
        ["opencli", "douyin", "user-videos", sec_uid, "--limit", str(limit), "-f", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def fmt(n: int) -> str:
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


def cmd_list_categories(creators: list[dict]):
    categories: dict[str, int] = {}
    for c in creators:
        cat = c.get("category", "未分类")
        categories[cat] = categories.get(cat, 0) + 1
    print("\n现有分类：")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}（{count} 人）")
    print()


def cmd_add(args):
    creators = load_watchlist()
    existing_names = [c["name"] for c in creators]
    if args.name in existing_names:
        print(f"[错误] 「{args.name}」已在 watchlist 中")
        sys.exit(1)

    new_creator = {
        "name": args.name,
        "platform": "douyin",
        "sec_uid": args.sec_uid,
        "user_id": "",
        "category": args.category,
        "added": date.today().isoformat(),
        "note": args.note or "",
    }
    creators.append(new_creator)
    save_watchlist(creators)
    print(f"已添加：{args.name}（{args.category}）")


def cmd_watch(args, creators: list[dict]):
    if args.name:
        creators = [c for c in creators if args.name in c["name"]]
        if not creators:
            print(f"[错误] watchlist 里没有找到「{args.name}」")
            sys.exit(1)

    if args.category:
        creators = [c for c in creators if c.get("category", "未分类") == args.category]
        if not creators:
            print(f"[错误] 分类「{args.category}」下没有创作者")
            sys.exit(1)

    douyin_creators = [c for c in creators if c["platform"] == "douyin"]
    if not douyin_creators:
        print("[错误] watchlist 里没有抖音创作者")
        sys.exit(1)

    for creator in douyin_creators:
        cat = creator.get("category", "未分类")
        print(f"\n{'='*62}")
        print(f"  {creator['name']}  [{cat}]  |  最近 {args.limit} 条 → Top {args.top} 按点赞")
        if creator.get("note"):
            print(f"  {creator['note']}")
        print(f"{'='*62}\n")

        videos = fetch_user_videos(creator["sec_uid"], args.limit)
        if not videos:
            print("  [错误] 未获取到数据，检查 opencli 是否已连接\n")
            continue

        videos.sort(key=lambda v: v.get("digg_count", 0), reverse=True)
        top = videos[:args.top]

        for i, v in enumerate(top, 1):
            title = v.get("title", "").replace("\n", " ").strip()[:52]
            digg = v.get("digg_count", 0)
            aweme_id = v.get("aweme_id", "")
            index = v.get("index", "?")
            duration = v.get("duration", 0)
            dur_str = f"{duration // 60}分{duration % 60}秒" if duration else "—"
            print(f"{i:2}. [赞:{fmt(digg)}] {title}")
            print(f"    时长:{dur_str}  最近第{index}条")
            print(f"    https://www.douyin.com/video/{aweme_id}")
            print()

        print(f"  共拉取 {len(videos)} 条，最高赞 {fmt(top[0]['digg_count'])} / 最低赞 {fmt(top[-1]['digg_count'])}")


def main():
    parser = argparse.ArgumentParser(description="创作者 watchlist — 抖音最新视频排名")
    parser.add_argument("--limit", type=int, default=20, help="每位创作者拉取最近几条视频（默认 20）")
    parser.add_argument("--top", type=int, default=5, help="每位创作者展示 Top N（默认 5）")
    parser.add_argument("--name", type=str, default=None, help="只查指定创作者（按名字匹配）")
    parser.add_argument("--category", type=str, default=None, help="只查指定分类")
    parser.add_argument("--list-categories", action="store_true", help="列出所有分类")
    parser.add_argument("--add", action="store_true", help="添加新创作者")
    parser.add_argument("--sec-uid", type=str, default=None, dest="sec_uid", help="添加时的 sec_uid")
    parser.add_argument("--note", type=str, default=None, help="添加时的备注")
    args = parser.parse_args()

    if args.list_categories:
        cmd_list_categories(load_watchlist())
        return

    if args.add:
        if not args.name or not args.sec_uid or not args.category:
            print("[错误] --add 需要同时提供 --name <名字> <sec_uid> --category <分类>")
            sys.exit(1)
        cmd_add(args)
        return

    cmd_watch(args, load_watchlist())


if __name__ == "__main__":
    main()
