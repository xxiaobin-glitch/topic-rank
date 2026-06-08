#!/usr/bin/env python3
"""
douyin-rank-custom.py
搜索抖音关键词视频，按自定义评分排名。数据源：MediaCrawler 关键词搜索。

用法：
  python3 douyin-rank-custom.py "AI视频"                         # 关键词搜索（时间加权，不限时间）
  python3 douyin-rank-custom.py "影视混剪" --no-time-weight      # 历史最高爆款
  python3 douyin-rank-custom.py "AI视频" --time-filter 7         # 只看近 1 周内
  python3 douyin-rank-custom.py --hot                            # 热点词 Top 10（仅词条，无视频排行）
  python3 douyin-rank-custom.py "AI视频" --score virality

时间过滤（--time-filter）：
  0    不限（默认）
  1    1 天内
  7    1 周内
  180  6 个月内

评分模式（--score）：
  value       留存价值：收藏×0.50 + 点赞×0.30 + 评论×0.20
  virality    传播力：分享×0.45 + 点赞×0.35 + 评论×0.20
  engagement  互动总量：点赞 + 收藏 + 评论 + 分享

时间加权（关键词模式默认开启）：
  分数除以发布天数，避免老内容霸榜。加 --no-time-weight 关闭。

注意：抖音接口不返回播放量，以互动数据为排名依据。
"""

import argparse

# 常用意图词 → 候选词组展开表
REQUIRE_EXPAND: dict[str, list[str]] = {
    "ai":   ["AI", "AIGC", "ai短片", "ai创作浪潮计划", "即梦", "可灵", "seedance", "kling", "ai漫剧", "ai生成", "抖音AI浪潮计划", "未来导演扶持计划"],
    "电影": ["电影", "电影感", "影视", "微电影", "短片", "cinematic"],
    "爱情": ["爱情", "恋爱", "情侣", "CP", "虐恋", "甜宠"],
    "搞笑": ["搞笑", "喜剧", "沙雕", "整活", "反转"],
    "励志": ["励志", "逆袭", "正能量", "奋斗", "坚持"],
    "高考": ["高考", "考生", "高三", "备考", "金榜", "题名", "上岸", "志愿", "填报"],
}
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime

TODAY_TS = time.time()

RESEARCH_DIR = os.path.expanduser(
    os.environ.get("TOPIC_RANK_RESEARCH_DIR", "~/topic-rank-research")
)

MEDIACRAWLER_DIR = os.path.expanduser(
    os.environ.get("MEDIACRAWLER_DIR", "~/Projects/MediaCrawler")
)
DY_CONFIG_PATH = os.path.join(MEDIACRAWLER_DIR, "config", "dy_config.py")
JSONL_DIR = os.path.join(MEDIACRAWLER_DIR, "data", "douyin", "jsonl")

VALID_TIME_FILTERS = {0, 1, 7, 180}  # MediaCrawler PUBLISH_TIME_TYPE 支持的值


BASE_CONFIG_PATH = os.path.join(MEDIACRAWLER_DIR, "config", "base_config.py")


def patch_configs(publish_time_type: int, max_notes: int) -> tuple[str, str]:
    """临时改写两个 config 文件，返回原始内容用于恢复。"""
    with open(DY_CONFIG_PATH) as f:
        dy_orig = f.read()
    with open(BASE_CONFIG_PATH) as f:
        base_orig = f.read()

    dy_patched = re.sub(
        r"^PUBLISH_TIME_TYPE\s*=\s*\d+",
        f"PUBLISH_TIME_TYPE = {publish_time_type}",
        dy_orig, flags=re.MULTILINE,
    )
    base_patched = re.sub(
        r"^CDP_CONNECT_EXISTING\s*=\s*\w+",
        "CDP_CONNECT_EXISTING = False",
        base_orig, flags=re.MULTILINE,
    )
    base_patched = re.sub(
        r"^CRAWLER_MAX_NOTES_COUNT\s*=\s*\d+",
        f"CRAWLER_MAX_NOTES_COUNT = {max_notes}",
        base_patched, flags=re.MULTILINE,
    )

    with open(DY_CONFIG_PATH, "w") as f:
        f.write(dy_patched)
    with open(BASE_CONFIG_PATH, "w") as f:
        f.write(base_patched)

    return dy_orig, base_orig


def restore_configs(dy_orig: str, base_orig: str) -> None:
    with open(DY_CONFIG_PATH, "w") as f:
        f.write(dy_orig)
    with open(BASE_CONFIG_PATH, "w") as f:
        f.write(base_orig)


TIME_FILTER_SECONDS = {1: 86400, 7: 7 * 86400, 180: 180 * 86400}


def run_mediacrawler(keyword: str, publish_time_type: int, time_filter_active: bool) -> bool:
    """运行 MediaCrawler 单关键词搜索，返回是否成功。"""
    max_notes = 45 if time_filter_active else 15
    dy_orig, base_orig = patch_configs(publish_time_type, max_notes)
    try:
        venv_python = os.path.join(MEDIACRAWLER_DIR, ".venv", "bin", "python3")
        python_bin = venv_python if os.path.exists(venv_python) else "python3"
        cmd = [
            python_bin, os.path.join(MEDIACRAWLER_DIR, "main.py"),
            "--platform", "dy",
            "--lt", "cookie",
            "--type", "search",
            "--keywords", keyword,
        ]
        result = subprocess.run(cmd, cwd=MEDIACRAWLER_DIR, timeout=600)
        if result.returncode != 0:
            print("[错误] MediaCrawler 运行失败", file=sys.stderr)
            return False
        return True
    finally:
        restore_configs(dy_orig, base_orig)


def read_today_jsonl(keywords: list[str], time_filter: int) -> list[dict]:
    """读取今天的 JSONL，合并所有关键词匹配的记录，按 time_filter 过滤发布时间。"""
    today = date.today().isoformat()
    jsonl_path = os.path.join(JSONL_DIR, f"search_contents_{today}.jsonl")
    if not os.path.exists(jsonl_path):
        files = sorted(
            [f for f in os.listdir(JSONL_DIR) if f.startswith("search_contents_") and f.endswith(".jsonl")],
            reverse=True,
        )
        if not files:
            print("[错误] 未找到 MediaCrawler 输出文件", file=sys.stderr)
            return []
        jsonl_path = os.path.join(JSONL_DIR, files[0])

    kw_lower = [k.lower() for k in keywords]
    cutoff = (TODAY_TS - TIME_FILTER_SECONDS[time_filter]) if time_filter > 0 else 0

    seen: set[str] = set()
    records: list[dict] = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                src_kw = (item.get("source_keyword") or "").lower()
                if not any(kw in src_kw for kw in kw_lower):
                    continue
                if cutoff and (item.get("create_time") or 0) < cutoff:
                    continue
                aweme_id = item.get("aweme_id")
                if aweme_id and aweme_id not in seen:
                    seen.add(aweme_id)
                    records.append(item)
            except json.JSONDecodeError:
                continue
    return records


def expand_require(terms: list[str]) -> list[list[str]]:
    """把每个 require 词展开为候选词组（AND 组之间，OR 组内）。"""
    result = []
    for t in terms:
        expanded = REQUIRE_EXPAND.get(t.lower(), [t])
        result.append([kw.lower() for kw in expanded])
    return result


def passes_require(video: dict, require_groups: list[list[str]]) -> bool:
    """视频在每个 require 组中至少匹配一个词才通过。"""
    if not require_groups:
        return True
    text = (video.get("title") or "").lower()
    for group in require_groups:
        if not any(kw in text for kw in group):
            return False
    return True


def llm_filter_videos(videos: list[dict], topic: str, candidate_n: int = 40) -> list[dict]:
    """用 DeepSeek API 对候选视频标题做语义相关性过滤。取已排序的前 candidate_n 条送审。"""
    import urllib.request

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[LLM过滤] 未设置 DEEPSEEK_API_KEY，跳过语义过滤", file=sys.stderr)
        return videos

    candidates = videos[:candidate_n]
    items_text = "\n".join(
        f"{i}. {(v.get('title') or v.get('desc') or '')[:80]}"
        for i, v in enumerate(candidates)
    )
    prompt = (
        f'你是内容筛选助手。判断下列抖音视频标题是否与"{topic}"相关。\n'
        f'只返回JSON数组，格式：[{{"id":0,"ok":true}},...]，不要其他内容。\n\n'
        f'{items_text}'
    )
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```[^\n]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content.strip())
        results = json.loads(content)
        relevant_ids = {r["id"] for r in results if r.get("ok")}
        filtered = [v for i, v in enumerate(candidates) if i in relevant_ids]
        print(f"[LLM过滤] {len(filtered)}/{len(candidates)} 条通过（主题：{topic}）")
        return filtered if filtered else candidates
    except Exception as e:
        print(f"[LLM过滤] 调用失败，跳过：{e}", file=sys.stderr)
        return videos


def compute_score(v: dict, mode: str, time_weight: bool) -> float:
    ts = v.get("create_time", 0)
    days = max((TODAY_TS - ts) / 86400, 1) if ts else 30
    d = days if time_weight else 1.0

    liked = int(v.get("liked_count") or 0)
    collected = int(v.get("collected_count") or 0)
    comments = int(v.get("comment_count") or 0)
    shared = int(v.get("share_count") or 0)

    if mode == "virality":
        raw = shared * 0.45 + liked * 0.35 + comments * 0.20
    elif mode == "value":
        raw = collected * 0.50 + liked * 0.30 + comments * 0.20
    elif mode == "engagement":
        raw = float(liked + collected + comments + shared)
    else:
        return 0.0
    return raw / d


SCORE_LABELS = {
    "value":      "留存价值（收藏×0.50 + 点赞×0.30 + 评论×0.20）",
    "virality":   "传播力（分享×0.45 + 点赞×0.35 + 评论×0.20）",
    "engagement": "互动总量（点赞 + 收藏 + 评论 + 分享）",
}


def fmt(n: int) -> str:
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


def fmt_days(ts: int) -> str:
    if not ts:
        return "未知"
    days = (TODAY_TS - ts) / 86400
    if days < 1:
        return f"{int(days * 24)}小时前"
    return f"{int(days)}天前"


def build_url(v: dict) -> str:
    aweme_id = v.get("aweme_id", "")
    sec_uid = v.get("sec_uid", "")
    if sec_uid:
        return f"https://www.douyin.com/user/{sec_uid}?modal_id={aweme_id}"
    return f"https://www.douyin.com/video/{aweme_id}"


def main():
    parser = argparse.ArgumentParser(description="抖音关键词视频排名（MediaCrawler）")
    parser.add_argument("keyword", nargs="*", help="搜索关键词，支持多个（--hot 模式下可省略）")
    parser.add_argument("--hot", action="store_true", help="拉取热点词 Top 10（仅词条列表，无视频）")
    parser.add_argument(
        "--score", choices=["value", "virality", "engagement"],
        default="value", help="评分模式（默认 value）",
    )
    parser.add_argument("--top", type=int, default=10, help="显示前 N 条（默认 10）")
    parser.add_argument("--limit", type=int, default=20, help="（保留参数，MediaCrawler 自行控制数量）")
    parser.add_argument("--no-time-weight", action="store_true", help="关闭时间加权")
    parser.add_argument(
        "--time-filter", type=int, default=0, choices=[0, 1, 7, 180],
        dest="time_filter",
        help="时间过滤：0=不限（默认）, 1=1天内, 7=1周内, 180=6个月内",
    )
    parser.add_argument("--save", action="store_true", help="保存结果到 TOPIC_RANK_RESEARCH_DIR")
    parser.add_argument(
        "--require", nargs="+", default=None, metavar="TERM",
        help="结果过滤：只保留标题含指定词的视频，多个词为 AND 逻辑；'ai' 自动展开为 AI 工具词组",
    )
    parser.add_argument(
        "--llm-filter", default=None, metavar="TOPIC", dest="llm_filter",
        help="用 DeepSeek LLM 对结果做语义过滤，参数为主题描述，如'高考相关的AI视频'",
    )
    args = parser.parse_args()

    # --hot 模式：仍用 opencli（热点词来自话题榜，MediaCrawler 不提供）
    if args.hot:
        import subprocess as sp, yaml
        result = sp.run(
            ["opencli", "douyin", "hashtag", "hot", "--limit", "10", "-f", "yaml"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[错误] hashtag hot 失败: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        items = yaml.safe_load(result.stdout) or []
        print(f"\n{'='*55}")
        print(f"  抖音热点词 Top {len(items)}")
        print(f"{'='*55}\n")
        for i, h in enumerate(items, 1):
            print(f"{i:2}. [热度:{fmt(h.get('view_count', 0))}] {h.get('name', '')}")
        print()
        return

    if not args.keyword:
        parser.error("请提供关键词，或使用 --hot 查看热点词")

    time_weight = not args.no_time_weight
    time_label = {0: "不限", 1: "1天内", 7: "1周内", 180: "6个月内"}[args.time_filter]
    kw_display = " + ".join(args.keyword)

    time_filter_active = args.time_filter != 0
    fetch_n = 45 if time_filter_active else 15
    for kw in args.keyword:
        print(f"\n运行 MediaCrawler 搜索「{kw}」（时间范围：{time_label}，抓取 {fetch_n} 条）...\n")
        ok = run_mediacrawler(kw, args.time_filter, time_filter_active)
        if not ok:
            sys.exit(1)

    videos = read_today_jsonl(args.keyword, args.time_filter)
    if not videos:
        print("[错误] 未从 JSONL 中找到匹配记录", file=sys.stderr)
        sys.exit(1)

    if args.require:
        require_groups = expand_require(args.require)
        before = len(videos)
        videos = [v for v in videos if passes_require(v, require_groups)]
        print(f"[过滤] --require {args.require}：{len(videos)}/{before} 条通过")
        if not videos:
            print("[错误] --require 过滤后无结果，尝试放宽条件", file=sys.stderr)
            sys.exit(1)

    for v in videos:
        v["score"] = compute_score(v, args.score, time_weight)

    videos.sort(key=lambda x: x["score"], reverse=True)

    if args.llm_filter:
        videos = llm_filter_videos(videos, args.llm_filter)

    top = videos[: args.top]

    if args.time_filter and not time_weight:
        mode_tag = f"{time_label}·绝对数字"
    elif not time_weight:
        mode_tag = "绝对数字"
    elif args.time_filter:
        mode_tag = f"{time_label}·时间加权"
    else:
        mode_tag = "时间加权"

    print(f"{'='*62}")
    print(f"  排名模式：{SCORE_LABELS[args.score]}  [{mode_tag}]")
    print(f"  关键词：{kw_display}  |  有效视频 {len(videos)} 条  |  Top {len(top)}")
    print(f"{'='*62}\n")

    for i, v in enumerate(top, 1):
        score_str = f"{v['score']:.1f}/天" if time_weight else f"{v['score']:.0f}分"
        title = (v.get("title") or v.get("desc") or "").replace("\n", " ")[:42]
        liked = int(v.get("liked_count") or 0)
        collected = int(v.get("collected_count") or 0)
        comments = int(v.get("comment_count") or 0)
        shared = int(v.get("share_count") or 0)
        ts = v.get("create_time", 0)
        print(f"{i:2}. [{score_str}] {title}")
        print(f"    赞:{fmt(liked)}  藏:{fmt(collected)}  评:{fmt(comments)}  享:{fmt(shared)}  发布:{fmt_days(ts)}")
        print(f"    作者: {v.get('nickname', '')}  →  {build_url(v)}")
        print()

    if args.save:
        today = date.today().isoformat()
        kw_slug = "+".join(args.keyword[:2]) if len(args.keyword) > 1 else args.keyword[0]
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        filepath = os.path.join(RESEARCH_DIR, f"{kw_slug}-抖音-{today}.md")
        lines = [f"# {kw_display} — 抖音 — {today}",
                 f"", f"> 模式：{args.score} [{mode_tag}]  |  Top {len(top)}", ""]
        for i, v in enumerate(top, 1):
            score_str = f"{v['score']:.1f}/天" if time_weight else f"{v['score']:.0f}分"
            title = (v.get("title") or v.get("desc") or "").replace("\n", " ")[:42]
            liked = int(v.get("liked_count") or 0)
            collected = int(v.get("collected_count") or 0)
            comments = int(v.get("comment_count") or 0)
            shared = int(v.get("share_count") or 0)
            lines += [f"{i}. **{title}**  `{score_str}`",
                      f"   赞:{fmt(liked)}  藏:{fmt(collected)}  评:{fmt(comments)}  享:{fmt(shared)}",
                      f"   作者: {v.get('nickname', '')} → [{build_url(v)}]({build_url(v)})", ""]
        with open(filepath, "w") as f:
            f.write("\n".join(lines))
        print(f"\n已保存：{filepath}")


if __name__ == "__main__":
    main()
