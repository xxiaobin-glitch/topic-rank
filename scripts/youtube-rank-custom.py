#!/usr/bin/env python3
"""
youtube-rank-custom.py
搜索 YouTube 某话题视频，按自定义评分排名。

用法：
  python3 youtube-rank-custom.py "视听语言"                          # 关键词搜索（时间加权）
  python3 youtube-rank-custom.py "film analysis" --no-time-weight    # 历史最高
  python3 youtube-rank-custom.py "AI video" --within 30              # 只看近 30 天

数据源：yt-dlp（无需 API key，不读 cookie）。分两阶段抓：
  1. --flat-playlist 粗搜（快，约 3 秒 / 60 条），只拿得到播放量
  2. 按播放量取前 N 条，并发补点赞/评论/发布日期（约 1 秒 / 条，并发 5）
  直接全量抓详情要 4.5 秒/条，50 条近 4 分钟，不可接受。

⚠️ 评分维度与其他平台不同：YouTube 只有 播放/点赞/评论，
   没有收藏、分享、投币。公式见 SCORE_LABELS，不要跨平台比分数。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

REQUIRE_EXPAND: dict[str, list[str]] = {
    "ai":   ["AI", "AIGC", "ai短片", "即梦", "可灵", "seedance", "kling", "ai生成", "ai video", "generative"],
    "电影": ["电影", "电影感", "影视", "微电影", "短片", "cinematic", "film", "movie", "cinema"],
    "爱情": ["爱情", "恋爱", "情侣", "CP", "虐恋", "甜宠", "romance"],
    "搞笑": ["搞笑", "喜剧", "沙雕", "整活", "反转", "comedy", "funny"],
    "励志": ["励志", "逆袭", "正能量", "奋斗", "坚持"],
}

RESEARCH_DIR = os.path.expanduser(
    os.environ.get("TOPIC_RANK_RESEARCH_DIR", "~/topic-rank-research")
)

SCORE_LABELS = {
    # 缺分享/收藏/投币，权重按剩余维度重新分配，与其他平台不可比
    "virality":        "传播力（点赞×0.60 + 评论×0.40）[YouTube 无分享数]",
    "value":           "留存价值（点赞×0.70 + 评论×0.30）[YouTube 无收藏/投币]",
    "engagement_rate": "互动率（(点赞+评论) / 播放量 × 1000）",
}

SCORE_UNIT = {"virality": "/天", "value": "/天", "engagement_rate": "‰"}


def expand_require(terms: list[str]) -> list[list[str]]:
    return [REQUIRE_EXPAND.get(t.lower(), [t]) for t in terms]


def passes_require(video: dict, require_groups: list[list[str]]) -> bool:
    title = (video.get("title") or "").lower()
    return all(any(w.lower() in title for w in group) for group in require_groups)


def fmt_int(n: int) -> str:
    return f"{n/10000:.1f}万" if n >= 10000 else str(n)


def ytdlp(args: list[str]) -> dict | None:
    """跑一次 yt-dlp 拿 JSON。失败返回 None，不抛异常——单条失败不该拖垮整批。"""
    try:
        r = subprocess.run(["yt-dlp", *args, "-J", "--no-warnings"],
                           capture_output=True, text=True, timeout=90)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except Exception:
        return None


def search_youtube(keyword: str, n: int) -> list[dict]:
    """阶段一：flat 粗搜，只拿 url / 标题 / 频道 / 播放量。"""
    data = ytdlp([f"ytsearch{n}:{keyword}", "--flat-playlist"])
    if not data:
        return []
    out = []
    for e in data.get("entries") or []:
        if not e or not e.get("url"):
            continue
        out.append({
            "title": e.get("title") or "",
            "up": e.get("channel") or e.get("uploader") or "",
            "view": e.get("view_count") or 0,
            "url": e.get("url"),
            "duration": e.get("duration") or 0,
        })
    return out


def fetch_detail(v: dict) -> dict:
    """阶段二：补点赞/评论/发布日期。取不到就留 0，条目仍保留。"""
    data = ytdlp([v["url"], "--skip-download"])
    if data:
        v["like"] = data.get("like_count") or 0
        v["reply"] = data.get("comment_count") or 0
        v["view"] = data.get("view_count") or v["view"]
        ud = data.get("upload_date")
        if ud:
            try:
                days = (datetime.now() - datetime.strptime(ud, "%Y%m%d")).days
                v["days"] = max(days, 0.5)
                v["upload_date"] = ud
            except ValueError:
                pass
    v.setdefault("like", 0)
    v.setdefault("reply", 0)
    v.setdefault("days", 1.0)
    return v


def compute_score(v: dict, mode: str, time_weight: bool) -> float:
    d = v["days"] if time_weight else 1.0
    if mode == "virality":
        return (v["like"] * 0.60 + v["reply"] * 0.40) / d
    if mode == "value":
        return (v["like"] * 0.70 + v["reply"] * 0.30) / d
    if mode == "engagement_rate":
        if v["view"] == 0:
            return 0.0
        return (v["like"] + v["reply"]) / v["view"] * 1000
    return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("keyword", nargs="+", help="搜索关键词，支持多个")
    parser.add_argument("--score", choices=["virality", "value", "engagement_rate"],
                        default="value", help="评分模式（默认 value）")
    parser.add_argument("--top", type=int, default=10, help="显示前 N 条（默认 10）")
    parser.add_argument("--fetch", type=int, default=60, help="粗搜抓取条数（默认 60）")
    parser.add_argument("--detail", type=int, default=25,
                        help="补详情的条数（默认 25，每条约 1 秒，调大明显变慢）")
    parser.add_argument("--no-time-weight", action="store_true", help="关闭时间加权")
    parser.add_argument("--within", type=int, default=None, help="只看近 N 天内发布")
    parser.add_argument("--save", action="store_true", help="保存到 TOPIC_RANK_RESEARCH_DIR")
    parser.add_argument("--require", nargs="+", default=None, help="标题必须含这些词（AND）")
    args = parser.parse_args()

    if not shutil_which("yt-dlp"):
        print("[错误] 没装 yt-dlp。装了才能查 YouTube：brew install yt-dlp", file=sys.stderr)
        sys.exit(1)

    time_weight = not args.no_time_weight
    kw_display = " + ".join(args.keyword)

    # 阶段一：多关键词分别粗搜，按 url 去重
    seen: dict[str, dict] = {}
    per_kw = max(args.fetch // len(args.keyword), 10)
    for kw in args.keyword:
        for v in search_youtube(kw, per_kw):
            seen.setdefault(v["url"], v)
    results = list(seen.values())

    if args.require:
        groups = expand_require(args.require)
        results = [v for v in results if passes_require(v, groups)]

    if not results:
        print("[错误] 没搜到结果（关键词太窄，或 yt-dlp 被限流）", file=sys.stderr)
        sys.exit(1)

    # 阶段二：按播放量取前 N 条补详情，并发 5
    results.sort(key=lambda v: v["view"], reverse=True)
    detail_pool = results[:args.detail]
    with ThreadPoolExecutor(max_workers=5) as pool:
        detail_pool = list(pool.map(fetch_detail, detail_pool))

    if args.within:
        detail_pool = [v for v in detail_pool if v["days"] <= args.within]
        if not detail_pool:
            print(f"[错误] 近 {args.within} 天内没有结果", file=sys.stderr)
            sys.exit(1)

    for v in detail_pool:
        v["score"] = compute_score(v, args.score, time_weight)
    detail_pool.sort(key=lambda v: v["score"], reverse=True)
    top = detail_pool[:args.top]

    label = SCORE_LABELS[args.score]
    if args.score == "engagement_rate":
        mode_tag = "互动率"
    elif not time_weight:
        mode_tag = "历史最高"
    elif args.within:
        mode_tag = f"近{args.within}天·时间加权"
    else:
        mode_tag = "时间加权"

    print(f"\n{'='*65}")
    print(f"  排名模式：{label}  [{mode_tag}]")
    print(f"  关键词：{kw_display}  |  共 {len(detail_pool)} 条  |  显示 Top {len(top)}")
    print(f"{'='*65}\n")

    for i, v in enumerate(top, 1):
        days_str = f"{int(v['days'])}天前" if v["days"] >= 1 else "今天"
        if args.score == "engagement_rate":
            score_str = f"{v['score']:.2f}‰"
        elif time_weight:
            score_str = f"{v['score']:.1f}/天"
        else:
            score_str = f"{v['score']:.0f}分"
        mins = int(v.get("duration") or 0) // 60
        print(f"{i:2}. [{score_str}] {v['title'][:38]}")
        print(f"    播:{fmt_int(v['view'])}  赞:{fmt_int(v['like'])}  评:{fmt_int(v['reply'])}  时长:{mins}分  发布:{days_str}")
        print(f"    频道: {v['up']}  →  {v['url']}")
        print()

    if args.save:
        today = date.today().isoformat()
        kw_slug = "+".join(args.keyword[:2]) if len(args.keyword) > 1 else args.keyword[0]
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        filepath = os.path.join(RESEARCH_DIR, f"{kw_slug}-YouTube-{today}.md")
        md = [f"# {kw_display} — YouTube — {today}", "",
              f"> 模式：{args.score} [{mode_tag}]  |  Top {len(top)}", ""]
        for i, v in enumerate(top, 1):
            days_str = f"{int(v['days'])}天前" if v["days"] >= 1 else "今天"
            if args.score == "engagement_rate":
                s = f"{v['score']:.2f}‰"
            elif time_weight:
                s = f"{v['score']:.1f}/天"
            else:
                s = f"{v['score']:.0f}分"
            md += [f"{i}. **{v['title'][:38]}**  `{s}`",
                   f"   播:{fmt_int(v['view'])}  赞:{fmt_int(v['like'])}  评:{fmt_int(v['reply'])}  发布:{days_str}",
                   f"   频道: {v['up']} → [{v['url']}]({v['url']})", ""]
        with open(filepath, "w") as f:
            f.write("\n".join(md))
        print(f"\n已保存：{filepath}")


def shutil_which(cmd: str) -> str | None:
    import shutil
    return shutil.which(cmd)


if __name__ == "__main__":
    main()
