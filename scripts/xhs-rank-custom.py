#!/usr/bin/env python3
"""
xhs-rank-custom.py
搜索小红书某话题笔记，或拉取平台热榜，按自定义评分排名。

用法：
  python3 xhs-rank-custom.py "AI视频"                        # 关键词搜索（时间加权）
  python3 xhs-rank-custom.py "影视混剪" --no-time-weight     # 历史最高爆款
  python3 xhs-rank-custom.py "AI视频" --within 10            # 只看近 10 天
  python3 xhs-rank-custom.py --hot                           # 平台综合热榜 Top 10
  python3 xhs-rank-custom.py --hot --category movie          # 指定分类热榜
  python3 xhs-rank-custom.py "AI视频" --score virality --type video

评分模式（--score）：
  value       留存价值：收藏×0.50 + 点赞×0.30 + 评论×0.20
  virality    传播力：分享×0.45 + 点赞×0.35 + 评论×0.20
  engagement  互动总量：点赞 + 收藏 + 评论 + 分享

  --hot 模式下只有点赞数据，固定按点赞排名。

时间加权（关键词模式默认开启）：
  所有分数除以发布天数，避免老内容霸榜。
  加 --no-time-weight 关闭，适合查历史最高。
"""

import argparse
import re
import subprocess
import sys
import time
from datetime import date

import yaml

TODAY = date.today()

XHS_HOT_CATEGORIES = [
    "fashion", "food", "cosmetics", "movie",
    "career", "love", "home", "gaming", "travel", "fitness",
]


def search_xhs(keyword: str, sort: str, note_type: str, page: int) -> list[dict]:
    args = ["xhs", "search", keyword, "--yaml", "--sort", sort, "--page", str(page)]
    if note_type != "all":
        args += ["--type", note_type]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[错误] xhs search 失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(result.stdout)
    return data.get("data", {}).get("items", [])


def hot_xhs(category: str | None) -> list[dict]:
    args = ["xhs", "hot", "--yaml"]
    if category:
        args += ["--category", category]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[错误] xhs hot 失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(result.stdout)
    return data.get("data", {}).get("items", [])


def parse_count(raw) -> int:
    s = str(raw).strip().replace("+", "").replace(",", "")
    if "万" in s:
        try:
            return int(float(s.replace("万", "")) * 10000)
        except ValueError:
            return 0
    try:
        return int(s)
    except ValueError:
        return 0


def parse_days(corner_tags: list) -> float:
    for tag in corner_tags:
        if tag.get("type") != "publish_time":
            continue
        text = tag.get("text", "").strip()

        m = re.match(r"(\d+)天前", text)
        if m:
            return max(float(m.group(1)), 1)

        m = re.match(r"(\d+)小时前", text)
        if m:
            return max(float(m.group(1)) / 24, 0.5)

        m = re.match(r"(\d+)分钟前", text)
        if m:
            return 0.5

        m = re.match(r"^(\d{1,2})-(\d{2})$", text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            try:
                pub = date(TODAY.year, month, day)
                if pub > TODAY:
                    pub = date(TODAY.year - 1, month, day)
                return max((TODAY - pub).days, 1)
            except ValueError:
                pass

        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            try:
                pub = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                return max((TODAY - pub).days, 1)
            except ValueError:
                pass

    return 30


def parse_item(item: dict) -> dict | None:
    if item.get("model_type") != "note":
        return None
    card = item.get("note_card", {})
    info = card.get("interact_info", {})
    user = card.get("user", {})
    title = card.get("display_title", "").strip()
    if not title:
        return None
    days = parse_days(card.get("corner_tag_info", []))
    return {
        "id": item.get("id", ""),
        "title": title,
        "author": user.get("nickname", ""),
        "type": card.get("type", ""),
        "like": parse_count(info.get("liked_count", 0)),
        "fav": parse_count(info.get("collected_count", 0)),
        "comment": parse_count(info.get("comment_count", 0)),
        "share": parse_count(info.get("shared_count", 0)),
        "days": days,
    }


def parse_hot_item(item: dict) -> dict | None:
    if item.get("model_type") != "note":
        return None
    card = item.get("note_card", {})
    info = card.get("interact_info", {})
    user = card.get("user", {})
    title = card.get("display_title", "").strip()
    if not title:
        return None
    return {
        "id": item.get("id", ""),
        "title": title,
        "author": user.get("nick_name") or user.get("nickname", ""),
        "type": card.get("type", ""),
        "like": parse_count(info.get("liked_count", 0)),
    }


def compute_score(v: dict, mode: str, time_weight: bool) -> float:
    d = v["days"] if time_weight else 1.0
    if mode == "virality":
        raw = v["share"] * 0.45 + v["like"] * 0.35 + v["comment"] * 0.20
    elif mode == "value":
        raw = v["fav"] * 0.50 + v["like"] * 0.30 + v["comment"] * 0.20
    elif mode == "engagement":
        raw = float(v["like"] + v["fav"] + v["comment"] + v["share"])
    else:
        return 0.0
    return raw / d


SCORE_LABELS = {
    "value":      "留存价值（收藏×0.50 + 点赞×0.30 + 评论×0.20）",
    "virality":   "传播力（分享×0.45 + 点赞×0.35 + 评论×0.20）",
    "engagement": "互动总量（点赞 + 收藏 + 评论 + 分享）",
}


def fmt(n: int) -> str:
    return f"{n/10000:.1f}万" if n >= 10000 else str(n)


def fmt_days(d: float) -> str:
    if d < 1:
        return f"{int(d*24)}小时前"
    return f"{int(d)}天前"


def main():
    parser = argparse.ArgumentParser(description="小红书话题排名 / 平台热榜")
    parser.add_argument("keyword", nargs="?", help="搜索关键词（--hot 模式下可省略）")
    parser.add_argument("--hot", action="store_true", help="拉取平台热榜，不需要关键词")
    parser.add_argument(
        "--category",
        choices=XHS_HOT_CATEGORIES,
        help="热榜分类（仅 --hot 模式有效）：fashion/food/cosmetics/movie/career/love/home/gaming/travel/fitness",
    )
    parser.add_argument(
        "--score",
        choices=["value", "virality", "engagement"],
        default="value",
        help="评分模式（默认 value，--hot 模式下无效）",
    )
    parser.add_argument(
        "--type",
        choices=["all", "video", "image"],
        default="all",
        help="笔记类型（默认 all，仅关键词模式有效）",
    )
    parser.add_argument(
        "--sort",
        choices=["general", "popular", "latest"],
        default="general",
        help="排序方式（默认 general，仅关键词模式有效）",
    )
    parser.add_argument("--top", type=int, default=10, help="显示前 N 条（默认 10）")
    parser.add_argument("--page", type=int, default=1, help="页码（默认 1，仅关键词模式有效；--within 模式下自动多翻页）")
    parser.add_argument("--no-time-weight", action="store_true", help="关闭时间加权（仅关键词模式有效）")
    parser.add_argument("--within", type=int, default=None, help="只看近 N 天内发布（自动多翻页抓取）")
    args = parser.parse_args()

    if args.hot:
        cat_label = args.category or "综合"
        print(f"\n拉取小红书热榜（{cat_label}）...\n")
        items = hot_xhs(args.category)
        results = [r for item in items if (r := parse_hot_item(item)) is not None]
        results.sort(key=lambda x: x["like"], reverse=True)
        top = results[: args.top]

        print(f"{'='*62}")
        print(f"  小红书热门推荐（非严格日榜，含历史热门）  [{cat_label}]  |  有效 {len(results)} 条  |  Top {len(top)}")
        print(f"{'='*62}\n")
        for i, v in enumerate(top, 1):
            tag = f"[{v['type']}]" if v["type"] else ""
            print(f"{i:2}. [赞:{fmt(v['like'])}] {tag} {v['title'][:42]}")
            print(f"    作者: {v['author']}  →  https://www.xiaohongshu.com/explore/{v['id']}")
            print()
        return

    if not args.keyword:
        parser.error("请提供关键词，或使用 --hot 查看热榜")

    time_weight = not args.no_time_weight

    if args.within:
        print(f"\n搜索「{args.keyword}」（近{args.within}天，类型:{args.type} 排序:{args.sort}，翻 3 页）...\n")
        raw_items = []
        for pg in range(1, 4):
            if pg > 1:
                time.sleep(1.5)
            page_items = search_xhs(args.keyword, args.sort, args.type, pg)
            raw_items.extend(page_items)
            print(f"  第 {pg} 页拿到 {len(page_items)} 条")
        print()
    else:
        print(f"\n搜索「{args.keyword}」（类型:{args.type} 排序:{args.sort} 页:{args.page}）...\n")
        raw_items = search_xhs(args.keyword, args.sort, args.type, args.page)

    print(f"拿到 {len(raw_items)} 条原始结果，过滤话题卡片、解析中...\n")

    results = []
    for item in raw_items:
        parsed = parse_item(item)
        if parsed:
            parsed["score"] = compute_score(parsed, args.score, time_weight)
            results.append(parsed)

    if args.within:
        results = [r for r in results if r["days"] <= args.within]

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[: args.top]

    if args.within and not time_weight:
        mode_tag = f"近{args.within}天·绝对数字"
    elif not time_weight:
        mode_tag = "绝对数字"
    elif args.within:
        mode_tag = f"近{args.within}天·时间加权"
    else:
        mode_tag = "时间加权"
    print(f"{'='*62}")
    print(f"  排名模式：{SCORE_LABELS[args.score]}  [{mode_tag}]")
    print(f"  关键词：{args.keyword}  |  有效笔记 {len(results)} 条  |  Top {len(top)}")
    print(f"{'='*62}\n")

    for i, v in enumerate(top, 1):
        tag = f"[{v['type']}]" if v["type"] else ""
        score_str = f"{v['score']:.1f}/天" if time_weight else f"{v['score']:.0f}分"
        print(f"{i:2}. [{score_str}] {tag} {v['title'][:40]}")
        print(f"    赞:{fmt(v['like'])}  藏:{fmt(v['fav'])}  评:{fmt(v['comment'])}  享:{fmt(v['share'])}  发布:{fmt_days(v['days'])}")
        print(f"    作者: {v['author']}  →  https://www.xiaohongshu.com/explore/{v['id']}")
        print()


if __name__ == "__main__":
    main()
