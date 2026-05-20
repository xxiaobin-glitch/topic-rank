#!/usr/bin/env python3
"""
watchlist.py
监控 watchlist.json 里的创作者，拉取最新视频，按点赞排名输出。

用法：
  python3 watchlist.py               # 所有创作者，拉最近 20 条，展示 Top 5
  python3 watchlist.py --limit 30    # 每人拉最近 30 条
  python3 watchlist.py --top 10      # 每人展示 Top 10
  python3 watchlist.py --name 编导李让  # 只查某一位

注意：抖音 user-videos 只返回点赞数，无收藏/分享/评论。
      视频按发布时间倒序（index=1 为最新），--limit 控制拉多少条。
"""

import argparse
import json
import os
import subprocess
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(TOOLS_DIR, "..", "data", "watchlist.json")


def load_watchlist() -> list[dict]:
    with open(WATCHLIST_FILE) as f:
        return json.load(f)["creators"]


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


def main():
    parser = argparse.ArgumentParser(description="创作者 watchlist — 抖音最新视频排名")
    parser.add_argument("--limit", type=int, default=20, help="每位创作者拉取最近几条视频（默认 20）")
    parser.add_argument("--top", type=int, default=5, help="每位创作者展示 Top N（默认 5）")
    parser.add_argument("--name", type=str, default=None, help="只查指定创作者（按名字匹配）")
    args = parser.parse_args()

    creators = load_watchlist()
    if args.name:
        creators = [c for c in creators if args.name in c["name"]]
        if not creators:
            print(f"[错误] watchlist 里没有找到「{args.name}」")
            sys.exit(1)

    douyin_creators = [c for c in creators if c["platform"] == "douyin"]
    if not douyin_creators:
        print("[错误] watchlist 里没有抖音创作者")
        sys.exit(1)

    for creator in douyin_creators:
        print(f"\n{'='*62}")
        print(f"  {creator['name']}  |  最近 {args.limit} 条 → Top {args.top} 按点赞")
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


if __name__ == "__main__":
    main()
