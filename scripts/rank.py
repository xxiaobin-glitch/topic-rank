#!/usr/bin/env python3
"""
rank.py
统一话题排行入口。搜索抖音 / B站 / 小红书，合并输出一份 Markdown 存档。

用法：
  python3 rank.py "seedance"                    # 三平台排行，保存到 research/
  python3 rank.py "AI视频" --platforms dy xhs   # 只跑抖音和小红书
  python3 rank.py "影视混剪" --no-time-weight   # 历史最高模式
  python3 rank.py "seedance" --score virality   # 传播力模式
  python3 rank.py "seedance" --within 10        # 只看近 10 天内容
  python3 rank.py "seedance" --no-save          # 只打印，不存文件
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
# 存档目录：优先读环境变量 TOPIC_RANK_RESEARCH_DIR，否则存到 ~/topic-rank-research/
RESEARCH_DIR = os.path.expanduser(
    os.environ.get("TOPIC_RANK_RESEARCH_DIR", "~/topic-rank-research")
)

PLATFORM_SCRIPTS = {
    "dy":  ("抖音",  "douyin-rank-custom.py"),
    "bili": ("B站",  "bili-rank-custom.py"),
    "xhs": ("小红书", "xhs-rank-custom.py"),
}


def within_to_time_filter(within: int) -> int:
    """把任意天数映射到 MediaCrawler 支持的时间档（抖音专用）。"""
    if within <= 1:
        return 1
    if within <= 7:
        return 7
    if within <= 180:
        return 180
    return 0


def run_platform(platform: str, script: str, keyword: list[str], score: str, top: int, no_time_weight: bool, within: int | None) -> tuple[str, bool]:
    """Run a platform script and return (stdout, success)."""
    cmd = ["python3", os.path.join(TOOLS_DIR, script)] + keyword + \
          ["--score", score, "--top", str(top)]
    if no_time_weight:
        cmd.append("--no-time-weight")
    if within:
        if platform == "dy":
            cmd.extend(["--time-filter", str(within_to_time_filter(within))])
        else:
            cmd.extend(["--within", str(within)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return f"[错误] {result.stderr.strip()}", False
    return result.stdout, True


def extract_results_block(output: str) -> str:
    """Extract the === results block and video entries from script output."""
    lines = output.splitlines()
    # find first === line
    start = next((i for i, l in enumerate(lines) if l.startswith("===")), None)
    if start is None:
        return output.strip()
    return "\n".join(lines[start:]).strip()


def results_to_markdown(platform_label: str, results_block: str, success: bool) -> str:
    if not success:
        return f"## {platform_label}\n\n{results_block}\n"

    lines = results_block.splitlines()
    md_lines = [f"## {platform_label}", ""]
    i = 0
    while i < len(lines):
        line = lines[i]
        # video entry line: " 1. [score] title"
        m = re.match(r"\s*(\d+)\.\s+\[(.+?)\]\s+(.*)", line)
        if m:
            rank, score_str, title = m.group(1), m.group(2), m.group(3)
            stats = lines[i + 1].strip() if i + 1 < len(lines) else ""
            author_line = lines[i + 2].strip() if i + 2 < len(lines) else ""
            # extract URL from author line
            url_match = re.search(r"https?://\S+", author_line)
            url = url_match.group(0) if url_match else ""
            author = re.sub(r"→.*", "", author_line).replace("作者:", "").strip()
            md_lines.append(f"{rank}. **{title.strip()}**  `{score_str}`")
            md_lines.append(f"   {stats}")
            if url:
                md_lines.append(f"   作者: {author} → [{url}]({url})")
            md_lines.append("")
            i += 4  # skip blank line after entry
            continue
        i += 1

    return "\n".join(md_lines)


def load_watchlist_names() -> set[str]:
    """返回 watchlist 里所有创作者名字（小写）。"""
    try:
        with open(WATCHLIST_FILE) as f:
            data = json.load(f)
        return {c["name"].lower() for c in data.get("creators", [])}
    except Exception:
        return set()


def parse_top_creators(output: str, platform_key: str) -> list[dict]:
    """从平台脚本输出中提取 Top 条目的作者和分数。"""
    creators = []
    lines = output.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(\d+)\.\s+\[(.+?)\]\s+(.*)", line)
        if m:
            rank = int(m.group(1))
            score_str = m.group(2)
            title = m.group(3).strip()
            author_line = lines[i + 2].strip() if i + 2 < len(lines) else ""
            author = re.sub(r"→.*", "", author_line)
            author = re.sub(r"作者:|UP:", "", author).strip()
            url_match = re.search(r"https?://\S+", author_line)
            url = url_match.group(0) if url_match else ""
            # 解析分数数值（去掉单位）
            score_val = re.search(r"[\d.]+", score_str)
            score = float(score_val.group(0)) if score_val else 0.0
            creators.append({
                "rank": rank, "score": score, "score_str": score_str,
                "title": title, "author": author, "url": url,
                "platform": platform_key,
            })
    return creators


def print_suggestions(platform_results: list[tuple[str, str, str, bool]], keyword: str) -> str:
    """打印分析与建议块，返回 Markdown 文本。"""
    watchlist = load_watchlist_names()
    platform_labels = {"dy": "抖音", "bili": "B站", "xhs": "小红书"}

    lines = ["\n" + "─" * 55, "  分析与建议", "─" * 55]
    md_lines = ["## 分析与建议", ""]

    # 各平台内容量
    count_parts = []
    all_creators: list[dict] = []
    for key, label, output, success in platform_results:
        if not success:
            count_parts.append(f"{label} 抓取失败")
            continue
        creators = parse_top_creators(output, key)
        count_parts.append(f"{label} {len(creators)} 条")
        all_creators.extend(creators)

    content_line = "内容量：" + " / ".join(count_parts)
    lines.append(content_line)
    md_lines.append(content_line)

    # 各平台 Top 1
    lines.append("")
    lines.append("各平台最强：")
    md_lines.append("")
    md_lines.append("**各平台最强：**")
    by_platform: dict[str, list[dict]] = {}
    for c in all_creators:
        by_platform.setdefault(c["platform"], []).append(c)
    for key, label, _, success in platform_results:
        if not success or key not in by_platform:
            continue
        top = by_platform[key][0]
        line = f"  {label}：{top['author']} 「{top['title'][:20]}…」 {top['score_str']}"
        lines.append(line)
        md_lines.append(line)

    # watchlist 建议：Top 3 中未追踪的高分创作者
    suggestions = [
        c for c in all_creators
        if c["rank"] <= 3 and c["author"] and c["author"].lower() not in watchlist
    ]
    # 按分数排序去重（同作者可能多平台出现）
    seen_authors: set[str] = set()
    unique_suggestions = []
    for c in sorted(suggestions, key=lambda x: x["score"], reverse=True):
        if c["author"] not in seen_authors:
            seen_authors.add(c["author"])
            unique_suggestions.append(c)

    if unique_suggestions:
        lines += ["", "可关注（未在 watchlist，排名靠前）："]
        md_lines += ["", "**可关注（未在 watchlist，排名靠前）：**"]
        for c in unique_suggestions:
            plat = platform_labels.get(c["platform"], c["platform"])
            line = f"  [{plat} #{c['rank']}] {c['author']}  {c['score_str']}  {c['url']}"
            lines.append(line)
            md_lines.append(line)
    else:
        lines.append("\n本次 Top 3 作者均已在 watchlist 中。")
        md_lines.append("\n本次 Top 3 作者均已在 watchlist 中。")

    lines.append("─" * 55)
    print("\n".join(lines))
    return "\n".join(md_lines)


def main():
    parser = argparse.ArgumentParser(description="三平台话题排行，合并存档")
    parser.add_argument("keyword", nargs="+", help="搜索关键词，支持多个（结果合并去重）")
    parser.add_argument(
        "--platforms", nargs="+", choices=["dy", "bili", "xhs"],
        default=["dy", "bili", "xhs"],
        help="指定平台（默认全部）：dy=抖音 bili=B站 xhs=小红书",
    )
    parser.add_argument(
        "--score", choices=["value", "virality", "engagement"],
        default="value", help="评分模式（默认 value）",
    )
    parser.add_argument("--top", type=int, default=10, help="每平台显示 Top N（默认 10）")
    parser.add_argument("--no-time-weight", action="store_true", help="关闭时间加权")
    parser.add_argument("--within", type=int, default=None, help="只看近 N 天内发布的内容（自动加大抓取量）")
    parser.add_argument("--no-save", action="store_true", help="只打印，不保存文件")
    args = parser.parse_args()

    today = date.today().isoformat()
    kw_display = " + ".join(args.keyword)
    kw_filename = args.keyword[0] if len(args.keyword) == 1 else "+".join(args.keyword[:2])
    if args.within and args.no_time_weight:
        mode_tag = f"近{args.within}天·绝对数字"
    elif args.no_time_weight:
        mode_tag = "历史最高"
    elif args.within:
        mode_tag = f"近{args.within}天·时间加权"
    else:
        mode_tag = "时间加权"
    print(f"\n{'='*55}")
    print(f"  话题：{kw_display}  |  模式：{args.score} [{mode_tag}]")
    print(f"  平台：{' / '.join(args.platforms)}  |  每平台 Top {args.top}")
    print(f"{'='*55}\n")

    md_sections = [
        f"# {kw_display} — {today}",
        f"",
        f"> 模式：{args.score} [{mode_tag}]  |  平台：{' / '.join(args.platforms)}  |  Top {args.top}",
        f"",
    ]

    platform_results = []
    for key in args.platforms:
        label, script = PLATFORM_SCRIPTS[key]
        print(f"--- {label} ---")
        output, success = run_platform(key, script, args.keyword, args.score, args.top, args.no_time_weight, args.within)
        print(output)
        block = extract_results_block(output)
        md_sections.append(results_to_markdown(label, block, success))
        platform_results.append((key, label, output, success))

    suggest_md = print_suggestions(platform_results, args.keyword)
    md_sections.append(suggest_md)

    if args.no_save:
        return

    os.makedirs(RESEARCH_DIR, exist_ok=True)
    filename = f"{kw_filename}-{today}.md"
    filepath = os.path.join(RESEARCH_DIR, filename)
    with open(filepath, "w") as f:
        f.write("\n".join(md_sections))

    print(f"\n已保存：{filepath}")


if __name__ == "__main__":
    main()
