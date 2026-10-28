#!/usr/bin/env python3
"""
comments.py
抓取抖音单条视频的高赞评论，按赞排序输出并存档。

用法：
  python3 comments.py "https://www.douyin.com/video/7671999699846532387"
  python3 comments.py 7671999699846532387 --count 100
  python3 comments.py <URL> --sub          # 连二级回复一起抓
  python3 comments.py <URL> --no-save      # 只打印不存档

设计取舍（2026-08-15 实测）：
  排行（rank.py）刻意不抓评论——排序只用赞/藏/评/享四个数字，评论正文一个字都不进计算，
  顺带抓会让一次排行从 46 秒涨到 6 分 56 秒，且每个视频只能拿到 ~10 条、还有重复。
  改成按需单抓：22 秒拿 50 条、零重复、可要二级回复，产出独立的 detail_comments 文件，
  不污染搜索缓存。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

MEDIACRAWLER_DIR = os.path.expanduser(
    os.environ.get("MEDIACRAWLER_DIR", "~/Projects/MediaCrawler")
)
JSONL_DIR = os.path.join(MEDIACRAWLER_DIR, "data", "douyin", "jsonl")
RESEARCH_DIR = os.path.expanduser(
    os.environ.get("TOPIC_RANK_RESEARCH_DIR", "~/topic-rank-research")
)


def extract_id(target: str) -> str:
    """从完整 URL 或裸 ID 里取出 aweme_id。支持 /video/<id> 与 ?modal_id=<id> 两种链接。"""
    m = re.search(r"modal_id=(\d+)", target) or re.search(r"/video/(\d+)", target)
    if m:
        return m.group(1)
    m = re.search(r"(\d{15,})", target)
    if m:
        return m.group(1)
    raise SystemExit(f"[错误] 无法从「{target}」解析出视频 ID")


def run_crawler(aweme_id: str, count: int, sub: bool) -> bool:
    venv_python = os.path.join(MEDIACRAWLER_DIR, ".venv", "bin", "python3")
    python_bin = venv_python if os.path.exists(venv_python) else sys.executable
    cmd = [
        python_bin, os.path.join(MEDIACRAWLER_DIR, "main.py"),
        "--platform", "dy",
        "--lt", "cookie",
        "--type", "detail",
        "--specified_id", aweme_id,
        "--get_comment", "yes",
        "--max_comments_count_singlenotes", str(count),
        "--headless", "yes",
    ]
    # 二级回复按「每条一级评论逐个翻页」抓，爆款视频动辄几千条回复，实测 10 分钟抓不完
    # （2026-08-15：某条 4524 回复的神评论直接跑满 600 秒）。所以 --sub 单独放宽超时。
    timeout = 1800 if sub else 600
    if sub:
        cmd += ["--get_sub_comment", "yes"]
        print("[提示] 已开启二级回复抓取。爆款视频的热评常有数千条回复，可能耗时十几分钟。\n")
    # 2026-08-30：同 douyin-rank-custom.py —— CDP 模式下 MediaCrawler 用 httpx 访问
    # 127.0.0.1:9222，shell 里有 HTTP_PROXY 而无 NO_PROXY 时本地回环也会走代理，
    # 表现为 CDP 启动失败后静默回退标准模式、报 chromium_headless_shell 不存在。
    child_env = os.environ.copy()
    no_proxy = child_env.get("NO_PROXY") or child_env.get("no_proxy") or ""
    for host in ("127.0.0.1", "localhost"):
        if host not in no_proxy:
            no_proxy = f"{no_proxy},{host}" if no_proxy else host
    child_env["NO_PROXY"] = no_proxy
    child_env["no_proxy"] = no_proxy

    try:
        result = subprocess.run(cmd, cwd=MEDIACRAWLER_DIR, timeout=timeout,
                                capture_output=True, text=True, env=child_env)
    except subprocess.TimeoutExpired:
        print(f"[错误] 抓取超过 {timeout} 秒未完成。"
              f"{'二级回复量过大，建议去掉 --sub 只抓一级评论。' if sub else ''}",
              file=sys.stderr)
        return False
    if result.returncode != 0:
        print("[错误] MediaCrawler 运行失败", file=sys.stderr)
        print(result.stdout[-2000:], file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        return False
    return True


def read_comments(aweme_id: str) -> list[dict]:
    """读当天 detail_comments，按 comment_id 去重（实测顺带抓会有重复，这里统一去重）。"""
    path = os.path.join(JSONL_DIR, f"detail_comments_{date.today().isoformat()}.jsonl")
    if not os.path.exists(path):
        return []
    uniq = {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if str(d.get("aweme_id")) == str(aweme_id):
            uniq[d.get("comment_id")] = d
    return list(uniq.values())


def read_video_meta(aweme_id: str) -> dict:
    path = os.path.join(JSONL_DIR, f"detail_contents_{date.today().isoformat()}.jsonl")
    if not os.path.exists(path):
        return {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if str(d.get("aweme_id")) == str(aweme_id):
            return d
    return {}


def fmt(n) -> str:
    n = int(n or 0)
    return f"{n/10000:.1f}万" if n >= 10000 else str(n)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取抖音单条视频的高赞评论")
    parser.add_argument("target", help="视频链接或 ID")
    parser.add_argument("--count", type=int, default=50, help="抓取一级评论条数（默认 50）")
    parser.add_argument("--sub", action="store_true", help="连二级回复一起抓")
    parser.add_argument("--top", type=int, default=30, help="显示 Top N（默认 30）")
    parser.add_argument("--no-save", action="store_true", help="只打印，不存档")
    args = parser.parse_args()

    aweme_id = extract_id(args.target)
    print(f"抓取视频 {aweme_id} 的评论（上限 {args.count} 条"
          f"{'，含二级回复' if args.sub else ''}）...\n")

    t0 = time.time()
    if not run_crawler(aweme_id, args.count, args.sub):
        return 1
    rows = read_comments(aweme_id)
    if not rows:
        print("[失败] 未取得任何评论，不写入报告文件。", file=sys.stderr)
        return 1

    meta = read_video_meta(aweme_id)
    title = (meta.get("title") or meta.get("desc") or "").replace("\n", " ").strip()
    author = meta.get("nickname") or "?"

    firsts = [c for c in rows if str(c.get("parent_comment_id") or "0") in ("0", "")]
    subs = [c for c in rows if c not in firsts]
    firsts.sort(key=lambda c: int(c.get("like_count") or 0), reverse=True)

    print("=" * 62)
    print(f"  {title[:50]}")
    print(f"  作者：{author}  |  评论 {len(firsts)} 条"
          f"{f'（+{len(subs)} 条二级回复）' if subs else ''}  |  {time.time()-t0:.0f} 秒")
    print("=" * 62 + "\n")
    for i, c in enumerate(firsts[:args.top], 1):
        print(f"{i:2}. [赞 {fmt(c.get('like_count'))} | 回复 {fmt(c.get('sub_comment_count'))}] "
              f"{c.get('content', '')[:60]}")

    if not args.no_save:
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        # 文件名只保留中英文数字：# 会被 Obsidian 当标签语法，空格和标点也会让链接难引用
        safe = re.sub(r"[^\w一-鿿]+", "", title)[:20] or aweme_id
        path = os.path.join(RESEARCH_DIR, f"{date.today().isoformat()}-评论-{safe}.md")
        L = [f"# 评论拆解 — {title[:60]}", "",
             f"> 作者：{author}  |  抓取时间：{date.today().isoformat()}  |  "
             f"一级评论 {len(firsts)} 条" + (f"，二级回复 {len(subs)} 条" if subs else ""), "",
             f"> 视频：https://www.douyin.com/user/{meta.get('sec_uid')}?modal_id={aweme_id}", "",
             f"> 数据：赞 {fmt(meta.get('liked_count'))} | 藏 {fmt(meta.get('collected_count'))} "
             f"| 评 {fmt(meta.get('comment_count'))} | 享 {fmt(meta.get('share_count'))}", "",
             "## 高赞评论", ""]
        for i, c in enumerate(firsts, 1):
            L.append(f"{i}. **[赞 {fmt(c.get('like_count'))} | 回复 {fmt(c.get('sub_comment_count'))}]** "
                     f"{c.get('content', '')}")
        if subs:
            L += ["", "## 二级回复", ""]
            for c in sorted(subs, key=lambda x: int(x.get("like_count") or 0), reverse=True):
                L.append(f"- [赞 {fmt(c.get('like_count'))}] {c.get('content', '')}")
        with open(path, "w") as f:
            f.write("\n".join(L))
        print(f"\n已保存：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
