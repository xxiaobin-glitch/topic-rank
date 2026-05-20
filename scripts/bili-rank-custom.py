#!/usr/bin/env python3
"""
bili-rank-custom.py
搜索 B站某话题视频，或拉取全站排行榜，按自定义评分排名。

用法：
  python3 bili-rank-custom.py "AI视频制作"                         # 关键词搜索（时间加权）
  python3 bili-rank-custom.py "罗翔" --no-time-weight --score value # 历史最高爆款
  python3 bili-rank-custom.py "AI视频" --within 10                  # 只看近 10 天
  python3 bili-rank-custom.py --hot                                 # 全站排行榜 Top 10
  python3 bili-rank-custom.py --hot --day 7 --top 20               # 7天榜 Top 20

评分模式（--score）：
  virality        传播力：分享×0.45 + 点赞×0.35 + 评论×0.20
  value           留存价值：收藏×0.40 + 投币×0.40 + 点赞×0.20
  engagement_rate 互动率：(点赞+投币+收藏+分享+评论) / 播放量 × 1000

时间加权（关键词模式默认开启）：
  所有分数除以发布天数，避免老内容霸榜。
  加 --no-time-weight 关闭，适合查历史最高。
  --hot 模式已是时间窗口榜单，不再额外加权。
"""

import argparse
import json
import sys
import time
import urllib.request
import subprocess

import yaml

import os
from datetime import date

TODAY_TS = time.time()
RESEARCH_DIR = os.path.expanduser(
    os.environ.get("TOPIC_RANK_RESEARCH_DIR", "~/topic-rank-research")
)


def search_bilibili(keyword: str, n: int, page: int) -> list[dict]:
    result = subprocess.run(
        ["bili", "search", keyword, "--type", "video", "-n", str(n),
         "--page", str(page), "--yaml"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[错误] bili search 失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(result.stdout)
    videos = data.get("data", [])
    return [v for v in videos if v.get("bvid")]


def hot_bilibili(day: int, n: int) -> list[dict]:
    result = subprocess.run(
        ["bili", "rank", "--day", str(day), "-n", str(n), "--yaml"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[错误] bili rank 失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(result.stdout)
    return data.get("data", {}).get("items", [])


def fetch_stats(bvid: str) -> dict | None:
    """调 B站公开 API 拿单条视频完整数据"""
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
            if d.get("code") != 0:
                return None
            info = d["data"]
            s = info["stat"]
            pubdate = info.get("pubdate", 0)
            days = max((TODAY_TS - pubdate) / 86400, 1) if pubdate else 30
            return {
                "bvid": bvid,
                "title": info["title"],
                "up": info["owner"]["name"],
                "url": f"https://www.bilibili.com/video/{bvid}",
                "view": s["view"],
                "like": s["like"],
                "coin": s["coin"],
                "fav": s["favorite"],
                "share": s["share"],
                "reply": s["reply"],
                "danmaku": s["danmaku"],
                "days": days,
            }
    except Exception as e:
        print(f"  [跳过] {bvid}: {e}", file=sys.stderr)
        return None


def compute_score(v: dict, mode: str, time_weight: bool) -> float:
    d = v["days"] if time_weight else 1.0

    if mode == "virality":
        return (v["share"] * 0.45 + v["like"] * 0.35 + v["reply"] * 0.20) / d

    elif mode == "value":
        return (v["fav"] * 0.40 + v["coin"] * 0.40 + v["like"] * 0.20) / d

    elif mode == "engagement_rate":
        if v["view"] == 0:
            return 0.0
        interactions = v["like"] + v["coin"] + v["fav"] + v["share"] + v["reply"]
        return interactions / v["view"] * 1000  # 互动率本身已归一化，不再除天数

    return 0.0


SCORE_LABELS = {
    "virality":        "传播力（分享×0.45 + 点赞×0.35 + 评论×0.20）",
    "value":           "留存价值（收藏×0.40 + 投币×0.40 + 点赞×0.20）",
    "engagement_rate": "互动率（互动总量 / 播放量 × 1000）",
}

SCORE_UNIT = {
    "virality":        "/天",
    "value":           "/天",
    "engagement_rate": "‰",
}


def fmt_int(n: int) -> str:
    return f"{n/10000:.1f}万" if n >= 10000 else str(n)


def main():
    parser = argparse.ArgumentParser(description="B站话题排名 / 全站排行榜")
    parser.add_argument("keyword", nargs="*", help="搜索关键词，支持多个（--hot 模式下可省略）")
    parser.add_argument("--hot", action="store_true", help="拉取全站排行榜，不需要关键词")
    parser.add_argument("--day", type=int, choices=[3, 7], default=3, help="排行周期：3 或 7 天（默认 3，仅 --hot 有效）")
    parser.add_argument(
        "--score",
        choices=["virality", "value", "engagement_rate"],
        default="value",
        help="评分模式（默认 value）"
    )
    parser.add_argument("--top", type=int, default=10, help="显示前 N 条（默认 10）")
    parser.add_argument("--fetch", type=int, default=20, help="搜索抓取条数（默认 20，仅关键词模式有效）")
    parser.add_argument("--page", type=int, default=1, help="搜索页码（默认 1，仅关键词模式有效）")
    parser.add_argument("--no-time-weight", action="store_true", help="关闭时间加权（仅关键词模式有效）")
    parser.add_argument("--within", type=int, default=None, help="只看近 N 天内发布（自动加大抓取量）")
    parser.add_argument("--save", action="store_true", help="保存结果到 TOPIC_RANK_RESEARCH_DIR")
    args = parser.parse_args()

    if args.hot:
        print(f"\n拉取 B站全站排行榜（近 {args.day} 天）...\n")
        items = hot_bilibili(args.day, max(args.top, 20))
        results = []
        for item in items:
            s = item.get("stats", {})
            owner = item.get("owner", {})
            view = s.get("view", 0)
            like = s.get("like", 0)
            coin = s.get("coin", 0)
            fav = s.get("favorite", 0)
            share = s.get("share", 0)
            reply = s.get("reply", 0)
            if args.score == "virality":
                score = share * 0.45 + like * 0.35 + reply * 0.20
            elif args.score == "engagement_rate":
                score = (like + coin + fav + share + reply) / view * 1000 if view else 0
            else:
                score = fav * 0.40 + coin * 0.40 + like * 0.20
            results.append({
                "title": item.get("title", ""),
                "up": owner.get("name", ""),
                "url": item.get("url", ""),
                "view": view, "like": like, "coin": coin,
                "fav": fav, "share": share, "reply": reply,
                "score": score,
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        top = results[: args.top]

        label = SCORE_LABELS[args.score]
        print(f"{'='*65}")
        print(f"  B站全站排行榜（近{args.day}天）  排名依据：{label}")
        print(f"  共 {len(results)} 条  |  显示 Top {len(top)}")
        print(f"{'='*65}\n")
        for i, v in enumerate(top, 1):
            if args.score == "engagement_rate":
                score_str = f"{v['score']:.2f}‰"
            else:
                score_str = f"{v['score']:.0f}分"
            print(f"{i:2}. [{score_str}] {v['title'][:42]}")
            print(f"    播:{fmt_int(v['view'])}  赞:{fmt_int(v['like'])}  币:{fmt_int(v['coin'])}  藏:{fmt_int(v['fav'])}  享:{fmt_int(v['share'])}")
            print(f"    UP: {v['up']}  →  {v['url']}")
            print()
        return

    if not args.keyword:
        parser.error("请提供关键词，或使用 --hot 查看全站排行榜")

    time_weight = not args.no_time_weight
    fetch_n = args.fetch * 3 if args.within else args.fetch
    kw_display = " + ".join(args.keyword)
    print(f"\n搜索「{kw_display}」，每词抓取 {fetch_n} 条，补全数据中...\n")

    seen_bvids: set[str] = set()
    videos_raw = []
    for kw in args.keyword:
        for v in search_bilibili(kw, fetch_n, args.page):
            if v["bvid"] not in seen_bvids:
                seen_bvids.add(v["bvid"])
                videos_raw.append(v)

    print(f"找到 {len(videos_raw)} 条有效视频（去重后），正在逐一查询完整数据...\n")

    results = []
    for i, v in enumerate(videos_raw, 1):
        bvid = v["bvid"]
        print(f"  [{i}/{len(videos_raw)}] {bvid} ...", end="\r")
        stats = fetch_stats(bvid)
        if stats:
            stats["score"] = compute_score(stats, args.score, time_weight)
            results.append(stats)
        time.sleep(0.35)

    if args.within:
        results = [r for r in results if r["days"] <= args.within]

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[: args.top]

    label = SCORE_LABELS[args.score]
    if args.within and not time_weight:
        mode_tag = f"近{args.within}天·绝对数字"
    elif not time_weight:
        mode_tag = "绝对数字"
    elif args.within:
        mode_tag = f"近{args.within}天·时间加权"
    else:
        mode_tag = "时间加权"

    print(f"\n{'='*65}")
    print(f"  排名模式：{label}  [{mode_tag}]")
    print(f"  关键词：{kw_display}  |  共 {len(results)} 条  |  显示 Top {len(top)}")
    print(f"{'='*65}\n")

    for i, v in enumerate(top, 1):
        days_str = f"{int(v['days'])}天前" if v["days"] >= 1 else f"{int(v['days']*24)}小时前"
        if args.score == "engagement_rate":
            score_str = f"{v['score']:.2f}‰"
        elif time_weight:
            score_str = f"{v['score']:.1f}/天"
        else:
            score_str = f"{v['score']:.0f}分"
        print(f"{i:2}. [{score_str}] {v['title'][:38]}")
        print(f"    播:{v['view']//10000:.1f}万  赞:{fmt_int(v['like'])}  币:{fmt_int(v['coin'])}  藏:{fmt_int(v['fav'])}  享:{fmt_int(v['share'])}  评:{fmt_int(v['reply'])}  发布:{days_str}")
        print(f"    UP: {v['up']}  →  {v['url']}")
        print()

    if args.save:
        today = date.today().isoformat()
        kw_slug = "+".join(args.keyword[:2]) if len(args.keyword) > 1 else args.keyword[0]
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        filepath = os.path.join(RESEARCH_DIR, f"{kw_slug}-B站-{today}.md")
        md = [f"# {kw_display} — B站 — {today}", "", f"> 模式：{args.score} [{mode_tag}]  |  Top {len(top)}", ""]
        for i, v in enumerate(top, 1):
            days_str = f"{int(v['days'])}天前" if v["days"] >= 1 else f"{int(v['days']*24)}小时前"
            if args.score == "engagement_rate":
                s = f"{v['score']:.2f}‰"
            elif time_weight:
                s = f"{v['score']:.1f}/天"
            else:
                s = f"{v['score']:.0f}分"
            md += [f"{i}. **{v['title'][:38]}**  `{s}`",
                   f"   播:{v['view']//10000:.1f}万  赞:{fmt_int(v['like'])}  币:{fmt_int(v['coin'])}  藏:{fmt_int(v['fav'])}  发布:{days_str}",
                   f"   UP: {v['up']} → [{v['url']}]({v['url']})", ""]
        with open(filepath, "w") as f:
            f.write("\n".join(md))
        print(f"\n已保存：{filepath}")


if __name__ == "__main__":
    main()
