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


def run_platform(platform: str, script: str, keyword: list[str], score: str, top: int,
                 no_time_weight: bool, within: int | None, require: list[str] | None = None,
                 llm_filter: str | None = None) -> tuple[str, bool]:
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
    if require:
        cmd.extend(["--require"] + require)
    if llm_filter and platform == "dy":
        cmd.extend(["--llm-filter", llm_filter])
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
            # 向前扫描找作者行，跳过多行标题、数据行等
            author = ""
            url = ""
            for j in range(i + 1, min(i + 10, len(lines))):
                candidate = lines[j].strip()
                if re.match(r"(作者:|UP:)", candidate):
                    author = re.sub(r"→.*", "", candidate)
                    author = re.sub(r"作者:|UP:", "", author).strip()
                    url_match = re.search(r"https?://\S+", candidate)
                    url = url_match.group(0) if url_match else ""
                    break
            title = m.group(3).strip()
            score_val = re.search(r"[\d.]+", score_str)
            score = float(score_val.group(0)) if score_val else 0.0
            sec_uid = ""
            if url:
                uid_match = re.search(r"/user/([^?&\s]+)", url)
                sec_uid = uid_match.group(1) if uid_match else ""
            creators.append({
                "rank": rank, "score": score, "score_str": score_str,
                "title": title, "author": author, "url": url,
                "platform": platform_key, "sec_uid": sec_uid,
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
        title = top.get('title') or top.get('name') or ''
        line = f"  {label}：{top['author']} 「{title[:20]}…」 {top['score_str']}"
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
        lines += ["", "→ 存入 watchlist（替换分类名后执行）："]
        for c in unique_suggestions:
            if c.get("sec_uid"):
                cmd = f"  python3 ~/.claude/skills/topic-rank/scripts/watchlist.py --add --name \"{c['author']}\" --sec-uid {c['sec_uid']} --category \"分类名\""
                lines.append(cmd)
    else:
        lines.append("\n本次 Top 3 作者均已在 watchlist 中。")
        md_lines.append("\n本次 Top 3 作者均已在 watchlist 中。")

    lines.append("─" * 55)
    print("\n".join(lines))
    return "\n".join(md_lines)


def run_query(keyword: list[str], platforms: list[str], score: str, top: int,
              no_time_weight: bool, within: int | None,
              require: list[str] | None = None,
              llm_filter: str | None = None) -> tuple[list, list[str], str]:
    """单次查询，返回 (platform_results, md_sections, suggest_md)。"""
    kw_display = " + ".join(keyword)
    if within and no_time_weight:
        mode_tag = f"近{within}天·绝对数字"
    elif no_time_weight:
        mode_tag = "历史最高"
    elif within:
        mode_tag = f"近{within}天·时间加权"
    else:
        mode_tag = "时间加权"

    print(f"\n{'='*55}")
    print(f"  话题：{kw_display}  |  模式：{score} [{mode_tag}]")
    print(f"  平台：{' / '.join(platforms)}  |  每平台 Top {top}")
    print(f"{'='*55}\n")

    md_sections = [
        f"> 模式：{score} [{mode_tag}]  |  平台：{' / '.join(platforms)}  |  Top {top}",
        "",
    ]

    platform_results = []
    for key in platforms:
        label, script = PLATFORM_SCRIPTS[key]
        print(f"--- {label} ---")
        output, success = run_platform(key, script, keyword, score, top, no_time_weight, within, require, llm_filter)
        print(output)
        block = extract_results_block(output)
        md_sections.append(results_to_markdown(label, block, success))
        platform_results.append((key, label, output, success))

    suggest_md = print_suggestions(platform_results, keyword)
    md_sections.append(suggest_md)
    return platform_results, md_sections, suggest_md


def parse_total_count(output: str) -> int:
    """从平台脚本输出中提取"有效视频 N 条"的总数。"""
    m = re.search(r"有效视频\s+(\d+)\s+条", output)
    return int(m.group(1)) if m else 0


def generate_compare_analysis(results_1d: list, results_7d: list) -> str:
    """根据两次查询结果生成对比分析，回答三个创作决策问题。"""
    creators_1d: list[dict] = []
    creators_7d: list[dict] = []
    vol_1d = 0
    vol_7d = 0
    for key, label, output, success in results_1d:
        if success:
            creators_1d.extend(parse_top_creators(output, key))
            vol_1d += parse_total_count(output)
    for key, label, output, success in results_7d:
        if success:
            creators_7d.extend(parse_top_creators(output, key))
            vol_7d += parse_total_count(output)

    if vol_1d == 0:
        vol_1d = len(creators_1d)
    if vol_7d == 0:
        vol_7d = len(creators_7d)
    ratio = vol_7d / vol_1d if vol_1d > 0 else 0

    lines = ["\n" + "─" * 55, "  选题分析", "─" * 55, ""]
    md_lines = ["## 选题分析", ""]

    # --- Q1：赛道现在处于什么阶段？---
    lines.append("【赛道阶段】")
    md_lines.append("### 赛道阶段")
    top1d = max(creators_1d, key=lambda c: c["score"], default=None)
    top7d = max(creators_7d, key=lambda c: c["score"], default=None)

    if ratio < 3:
        if top7d and top7d["score"] > 5000:
            stage = f"起势期——7天头部已有爆款（{top7d['author']} {top7d['score_str']}），但近1天跟进内容不多，说明赛道刚被验证，还没大量涌入，现在入场时机好"
        else:
            stage = f"观察期——7天头部得分不高，话题热度有限，谨慎跟进"
    elif ratio < 8:
        stage = f"活跃期——1天 {vol_1d} 条 / 7天 {vol_7d} 条，持续有新内容涌入，赛道竞争开始但未饱和"
    else:
        stage = f"退潮期——7天内容量是1天的 {ratio:.0f} 倍，高峰已过，跟进风险较大"

    lines.append(f"  {stage}")
    md_lines.append(stage)
    md_lines.append("")

    # --- Q2：什么内容格式在跑量？---
    lines.append("")
    lines.append("【跑量格式】")
    md_lines.append("### 跑量格式")

    # 从7天 top 内容里提取格式信号
    format_signals = []
    for c in creators_7d[:10]:
        title = c.get("title", "")
        tags = re.findall(r"#(\S+?)(?=\s|#|$)", title)
        format_signals.extend(tags)

    # 检测 AI 标签
    ai_creators = [c for c in creators_7d[:10] if re.search(r"#ai|#aigc|#AI", c.get("title", ""), re.I)]
    ai_count = len(ai_creators)

    # 高收藏率内容（留存型）
    high_save = [c for c in creators_7d[:10] if c["score"] > 3000]

    if ai_count > 0:
        ai_line = f"7天 Top10 中有 {ai_count} 条明确标注 AI（{' / '.join(c['author'] for c in ai_creators[:3])}），AI 制作已被算法接受"
        lines.append(f"  {ai_line}")
        md_lines.append(ai_line)

    if high_save:
        top_titles = "、".join(f"「{c.get('title','')[:15]}」" for c in high_save[:3])
        save_line = f"得分 3000+ 的内容：{top_titles}——末世具体场景+爽感直给是主流公式"
        lines.append(f"  {save_line}")
        md_lines.append(save_line)
    md_lines.append("")

    # --- Q3：差异化切入点 ---
    lines.append("")
    lines.append("【差异化空间】")
    md_lines.append("### 差异化空间")

    authors_1d = {c["author"] for c in creators_1d[:5] if c["author"]}
    authors_7d_top = {c["author"] for c in creators_7d[:5] if c["author"]}
    overlap = authors_1d & authors_7d_top

    if overlap:
        overlap_line = f"持续产出者：{'、'.join(overlap)}——头部已有稳定创作者，差异化要在角度或形式上找，不能照搬"
    else:
        overlap_line = "1天和7天 Top5 无重叠——头部未固化，跑量靠内容质量而非账号积累，入场门槛低"
    lines.append(f"  {overlap_line}")
    md_lines.append(overlap_line)

    # watchlist 建议（只在终端输出，不进文件）
    all_top = creators_1d[:3] + creators_7d[:3]
    seen: set[str] = set()
    watchlist = load_watchlist_names()
    suggestions = []
    for c in all_top:
        if c["author"] and c["author"] not in seen and c["author"].lower() not in watchlist and c.get("sec_uid"):
            seen.add(c["author"])
            suggestions.append(c)

    if suggestions:
        lines += ["", "→ 存入 watchlist（替换分类名后执行）："]
        for c in suggestions:
            lines.append(f"  python3 ~/.claude/skills/topic-rank/scripts/watchlist.py --add --name \"{c['author']}\" --sec-uid {c['sec_uid']} --category \"分类名\"")

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
    parser.add_argument("--within", type=int, default=None, help="只看近 N 天内发布的内容")
    parser.add_argument("--no-save", action="store_true", help="只打印，不保存文件")
    parser.add_argument("--compare", action="store_true", help="1天+7天联查，生成对比分析（用于选题决策）")
    parser.add_argument(
        "--require", nargs="+", default=None, metavar="TERM",
        help="结果过滤：只保留标题含指定词的视频，多个词为 AND 逻辑；'ai' 自动展开为 AI 工具词组",
    )
    parser.add_argument(
        "--llm-filter", default=None, metavar="TOPIC", dest="llm_filter",
        help="用 DeepSeek LLM 对抖音结果做语义过滤，参数为主题描述，如'高考相关的AI视频'",
    )
    args = parser.parse_args()

    today = date.today().isoformat()
    kw_display = " + ".join(args.keyword)
    kw_filename = args.keyword[0] if len(args.keyword) == 1 else "+".join(args.keyword[:2])

    if args.compare:
        print(f"\n{'#'*55}")
        print(f"  选题研究模式：{kw_display}  |  1天 + 7天联查")
        print(f"{'#'*55}")

        print(f"\n\n{'━'*55}  1天数据  {'━'*55}\n")
        results_1d, md_1d, _ = run_query(args.keyword, args.platforms, args.score, args.top, args.no_time_weight, 1, args.require, args.llm_filter)

        print(f"\n\n{'━'*55}  7天数据  {'━'*55}\n")
        top_7d = max(args.top, 20)
        results_7d, md_7d, _ = run_query(args.keyword, args.platforms, args.score, top_7d, args.no_time_weight, 7, args.require, args.llm_filter)

        compare_md = generate_compare_analysis(results_1d, results_7d)

        if not args.no_save:
            os.makedirs(RESEARCH_DIR, exist_ok=True)
            filename = f"{today}-{kw_filename}.md"
            filepath = os.path.join(RESEARCH_DIR, filename)
            # md_1d 和 md_7d 的最后一段是"分析与建议"（watchlist 操作提示），存档时去掉
            def strip_suggestions(sections: list[str]) -> list[str]:
                for i, s in enumerate(sections):
                    if s.startswith("## 分析与建议"):
                        return sections[:i]
                return sections
            with open(filepath, "w") as f:
                f.write(f"# {kw_display} — {today}\n\n")
                f.write("> 选题研究模式：1天 + 7天联查\n\n")
                f.write("## 1天 Top 10\n\n")
                f.write("\n".join(strip_suggestions(md_1d)))
                f.write(f"\n\n## 7天 Top 20\n\n")
                f.write("\n".join(strip_suggestions(md_7d)))
                f.write("\n\n")
                f.write(compare_md)
            print(f"\n已保存：{filepath}")
        return

    # 普通单次查询
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
        output, success = run_platform(key, script, args.keyword, args.score, args.top, args.no_time_weight, args.within, args.require, args.llm_filter)
        print(output)
        block = extract_results_block(output)
        md_sections.append(results_to_markdown(label, block, success))
        platform_results.append((key, label, output, success))

    suggest_md = print_suggestions(platform_results, args.keyword)
    md_sections.append(suggest_md)

    if args.no_save:
        return

    os.makedirs(RESEARCH_DIR, exist_ok=True)
    filename = f"{today}-{kw_filename}.md"
    filepath = os.path.join(RESEARCH_DIR, filename)
    with open(filepath, "w") as f:
        f.write("\n".join(md_sections))

    print(f"\n已保存：{filepath}")


if __name__ == "__main__":
    main()
