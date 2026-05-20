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
import os
import re
import subprocess
import sys
from datetime import date

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
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


def run_platform(platform: str, script: str, keyword: str, score: str, top: int, no_time_weight: bool, within: int | None) -> tuple[str, bool]:
    """Run a platform script and return (stdout, success)."""
    cmd = ["python3", os.path.join(TOOLS_DIR, script), keyword,
           "--score", score, "--top", str(top)]
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


def main():
    parser = argparse.ArgumentParser(description="三平台话题排行，合并存档")
    parser.add_argument("keyword", help="搜索关键词")
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
    if args.within and args.no_time_weight:
        mode_tag = f"近{args.within}天·绝对数字"
    elif args.no_time_weight:
        mode_tag = "历史最高"
    elif args.within:
        mode_tag = f"近{args.within}天·时间加权"
    else:
        mode_tag = "时间加权"
    print(f"\n{'='*55}")
    print(f"  话题：{args.keyword}  |  模式：{args.score} [{mode_tag}]")
    print(f"  平台：{' / '.join(args.platforms)}  |  每平台 Top {args.top}")
    print(f"{'='*55}\n")

    md_sections = [
        f"# {args.keyword} — {today}",
        f"",
        f"> 模式：{args.score} [{mode_tag}]  |  平台：{' / '.join(args.platforms)}  |  Top {args.top}",
        f"",
    ]

    for key in args.platforms:
        label, script = PLATFORM_SCRIPTS[key]
        print(f"--- {label} ---")
        output, success = run_platform(key, script, args.keyword, args.score, args.top, args.no_time_weight, args.within)
        print(output)
        block = extract_results_block(output)
        md_sections.append(results_to_markdown(label, block, success))

    if args.no_save:
        return

    os.makedirs(RESEARCH_DIR, exist_ok=True)
    filename = f"{args.keyword}-{today}.md"
    filepath = os.path.join(RESEARCH_DIR, filename)
    with open(filepath, "w") as f:
        f.write("\n".join(md_sections))

    print(f"\n已保存：{filepath}")


if __name__ == "__main__":
    main()
