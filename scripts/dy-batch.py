#!/usr/bin/env python3
"""
抖音多标签批量抓取 + 多时间窗口排名 + 趋势对照表。

为什么要它（2026-10-27）：
- 多个词连着搜会被限流（后面的词 0 条且不报错），要逐个抓、中间隔一段时间
- 每步打印 [i/N  NN%]，用 tools/progress/run-task 启动时菜单栏有进度
- 抓完用 douyin-rank-custom.py --no-crawl 合并出各窗口的榜，再出对照表

对照表的趋势不看名次：各窗口的榜用的是同一批数字、同一个分数公式，
名次差只是因为竞争者不同。趋势看同一条视频在当天多次抓取之间的增速：
  近期速度 = 两次快照之间的点赞增量 / 间隔小时
  平均速度 = 最新点赞 / 发布至今小时
  加速比   = 近期 / 平均（>=1.2 加速，<0.8 放缓；放缓是常态）
快照读近 3 天的 JSONL，间隔越长越可靠——今晚一轮、明早一轮最好。

用法：
  R=~/Projects/tools/progress/run-task
  $R "抖音AI剧情" -- python3 dy-batch.py ai创作浪潮计划 libtv ai短片 \\
      --windows 1 3 --top 30 --llm-filter "有剧情故事的AI短片"
  只重出榜和对照表、不抓：加 --no-crawl
  用预设（标签、过滤词、窗口存在 data/dy-presets.json）：
  $R "抖音AI剧情榜" -- python3 dy-batch.py --preset ai剧情
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

HERE = os.path.dirname(os.path.abspath(__file__))
DY = os.path.join(HERE, "douyin-rank-custom.py")
JSONL_DIR = os.path.expanduser("~/Projects/MediaCrawler/data/douyin/jsonl")
PRESETS = os.path.join(os.path.dirname(HERE), "data", "dy-presets.json")
RESEARCH_DIR = os.path.expanduser(os.environ.get("TOPIC_RANK_RESEARCH_DIR", "~/topic-rank-research"))


def tier_for(within: int) -> int:
    """抖音只有 1/7/180 天抓取档。"""
    return 1 if within <= 1 else 7 if within <= 7 else 180


def load_records(days: int = 1) -> list[dict]:
    """读最近 days 天的 JSONL（MediaCrawler 一天一个文件）。抓取计数只看当天；
    趋势要跨天的快照——今晚抓一轮、明早再抓一轮，间隔够长加速比才可靠。"""
    out = []
    for d in range(days):
        day = date.fromordinal(date.today().toordinal() - d).isoformat()
        path = os.path.join(JSONL_DIR, f"search_contents_{day}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def count_kw(kw: str) -> int:
    """按 source_keyword 精确计数（脚本里的「有效视频」是子串匹配，会把长词的数据算进短词）。"""
    return len({r["aweme_id"] for r in load_records() if r.get("source_keyword") == kw})


def crawl(keywords: list[str], tiers: list[int], gap: int) -> None:
    steps = [(kw, t) for kw in keywords for t in tiers]
    n = len(steps)
    for i, (kw, t) in enumerate(steps, 1):
        before = count_kw(kw)
        subprocess.run([sys.executable, DY, kw, "--time-filter", str(t), "--top", "1"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        after = count_kw(kw)
        pct = round(i / n * 90)  # 留 10% 给排名和对照表
        print(f"[{i}/{n}  {pct}%] {kw} {t}天档 新增{after - before} 累计{after}", flush=True)
        if t == tiers[-1] and after == 0:
            print(f"[停止抓取] {kw} 各档都是 0 条，疑似被限流；用已抓到的数据出榜", flush=True)
            return
        if i < n:
            time.sleep(gap)


def rank(keywords: list[str], within: int, top: int, llm: str | None, save: bool,
         exclude: list[str] | None = None) -> list[str]:
    """跑一次合并排名，返回按名次排列的 aweme_id。输出写日志文件不打到屏幕——
    标题里可能带「10%」之类，会被菜单栏当成进度。"""
    cmd = [sys.executable, DY, *keywords, "--no-crawl", "--time-filter", str(tier_for(within)),
           "--top", str(top)]
    if within != tier_for(within):
        cmd += ["--within", str(within)]
    if llm:
        cmd += ["--llm-filter", llm]
    if exclude:
        cmd += ["--exclude-uid", *exclude]
    if save:
        cmd.append("--save")
    res = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"已保存：(.+)", res.stdout)
    print(f"  近{within}天榜：{m.group(1) if m else '（未保存）'}", flush=True)
    ex = re.search(r"\[排除\] (.+)", res.stdout)
    if ex:
        print(f"    排除 {ex.group(1)}", flush=True)
    if res.returncode != 0:
        print(f"  [错误] 近{within}天榜失败：{res.stderr.strip()[-300:]}", flush=True)
        return []
    return re.findall(r"modal_id=(\d+)", res.stdout)


def trend(aweme_id: str, snaps: dict[str, list[dict]]) -> dict:
    s = sorted(snaps.get(aweme_id, []), key=lambda r: r.get("last_modify_ts") or 0)
    last = s[-1]
    liked = int(last.get("liked_count") or 0)
    age_h = max((last["last_modify_ts"] / 1000 - (last.get("create_time") or 0)) / 3600, 0.1)
    info = {"rec": last, "liked": liked, "age_h": age_h, "avg": liked / age_h,
            "recent": None, "ratio": None, "span_min": 0}
    first = s[0]
    span_h = (last["last_modify_ts"] - first["last_modify_ts"]) / 3_600_000
    info["span_min"] = round(span_h * 60)
    if span_h >= 20 / 60:  # 间隔不到 20 分钟噪声太大，不算
        info["recent"] = (liked - int(first.get("liked_count") or 0)) / span_h
        info["ratio"] = info["recent"] / info["avg"] if info["avg"] else None
    return info


def label(ratio: float | None) -> str:
    # 视频点赞多集中在刚发出那段，近期速度低于发布以来平均是常态，所以「放缓」不是坏信号，只有「加速」值得看
    if ratio is None:
        return "数据不足"
    return "↑ 加速" if ratio >= 1.2 else "↓ 放缓" if ratio < 0.8 else "→ 保持"


def fmt(n: float) -> str:
    return f"{n / 10000:.1f}万" if n >= 10000 else f"{n:.0f}"


def compare(keywords: list[str], ranks: dict[int, list[str]]) -> str:
    snaps: dict[str, list[dict]] = {}
    for r in load_records(days=3):
        if r.get("last_modify_ts"):
            snaps.setdefault(r["aweme_id"], []).append(r)
    wins = sorted(ranks)
    pos = {w: {a: i + 1 for i, a in enumerate(ids)} for w, ids in ranks.items()}
    ids: list[str] = []
    for w in wins:
        ids += [a for a in ranks[w] if a not in ids]
    # 排序：几个榜都在的在前（按最短窗口名次），其余按各自名次
    ids.sort(key=lambda a: (-sum(a in pos[w] for w in wins),
                            min(pos[w].get(a, 999) for w in wins)))

    today = date.today().isoformat()
    head = " | ".join(f"近{w}天" for w in wins)
    lines = [f"# 抖音 {' / '.join(f'近{w}天' for w in wins)} 对照 — {today}", "",
             f"> 标签：{' + '.join(keywords)}", ">",
             "> 怎么读名次：发布超过 1 天还能挤进更长窗口的榜（如 3 天榜、7 天榜）= 火得久；几个窗口都靠前 = 持续火。",
             "> 名次不说明是否在上升：今天发的视频在各窗口分数相同（同一次抓取、同一公式），在长窗口名次只会持平或下降——那只是前几天的爆款进来抢位置，说明的是它能不能打过老视频。",
             "> 趋势看「加速比」= 近期每小时涨赞 ÷ 发布以来平均每小时涨赞：≥1.2 加速，<0.8 放缓。",
             "> 点赞多集中在刚发出那段，「放缓」是大多数视频的常态；只有「加速」说明增速在变快（可能被再次推荐），值得看。",
             "> 近期速度取近 3 天内第一次和最后一次抓到它之间的增量；间隔不足 20 分钟记「数据不足」。",
             "> 要看趋势就隔几个小时再跑一轮（如今晚一轮、明早一轮），间隔越长越可靠。", "",
             f"| # | 视频 | 作者 | {head} | 发布 | 赞 | 平均赞/时 | 近期赞/时 | 快照跨度 | 加速比 | 趋势 |",
             "|" + "---|" * (10 + len(wins))]
    rising = []
    for i, a in enumerate(ids, 1):
        t = trend(a, snaps)
        r = t["rec"]
        title = (r.get("title") or r.get("desc") or "").replace("\n", " ").replace("|", "／")[:28]
        url = f"https://www.douyin.com/user/{r.get('sec_uid')}?modal_id={a}"
        cells = " | ".join(str(pos[w].get(a, "—")) for w in wins)
        age = f"{t['age_h']:.0f}小时前" if t["age_h"] < 48 else f"{t['age_h'] / 24:.0f}天前"
        recent = fmt(t["recent"]) if t["recent"] is not None else "—"
        ratio = f"{t['ratio']:.2f}" if t["ratio"] is not None else "—"
        lines.append(f"| {i} | [{title}]({url}) | {r.get('nickname', '')} | {cells} | {age} | "
                     f"{fmt(t['liked'])} | {fmt(t['avg'])} | {recent} | {t['span_min']}分 | {ratio} | {label(t['ratio'])} |")
        if t["ratio"] is not None and t["ratio"] >= 1.2:
            rising.append((t["ratio"], title, r.get("nickname", "")))
    lines += ["", "## 加速中（加速比 ≥ 1.2）", ""]
    lines += [f"- {x:.2f}× {t}（{n}）" for x, t, n in sorted(rising, reverse=True)] or ["- 无"]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description="抖音多标签批量抓取 + 多窗口排名 + 趋势对照表")
    p.add_argument("keyword", nargs="*")
    p.add_argument("--preset", default=None, help="用 data/dy-presets.json 里的预设（命令行参数优先）")
    p.add_argument("--windows", type=int, nargs="+", default=None, help="排名窗口天数（默认 1 3）")
    p.add_argument("--top", type=int, default=None, help="每个窗口 Top N（默认 30）")
    p.add_argument("--gap", type=int, default=90, help="每次搜索间隔秒数（默认 90，防限流）")
    p.add_argument("--llm-filter", dest="llm", default=None)
    p.add_argument("--no-crawl", action="store_true", help="不抓，只用当天已抓数据出榜和对照表")
    p.add_argument("--no-save", action="store_true")
    a = p.parse_args()
    if a.preset:
        with open(PRESETS) as f:
            presets = json.load(f)
        if a.preset not in presets:
            p.error(f"没有预设「{a.preset}」，可选：{'、'.join(presets)}")
        pr = presets[a.preset]
        a.keyword = a.keyword or pr["keywords"]
        a.llm = a.llm or pr.get("llm_filter")
        a.windows = a.windows or pr.get("windows")
        a.top = a.top or pr.get("top")
        ex_path = os.path.join(os.path.dirname(PRESETS), "dy-exclude.json")  # 个人数据，不进 git
        ex_all = json.load(open(ex_path)) if os.path.exists(ex_path) else {}
        a.exclude = [e["sec_uid"] for e in ex_all.get(a.preset, [])]
    else:
        a.exclude = []
    if not a.keyword:
        p.error("请给关键词，或用 --preset")
    a.windows = a.windows or [1, 3]
    a.top = a.top or 30

    tiers = sorted({tier_for(w) for w in a.windows})
    if not a.no_crawl:
        crawl(a.keyword, tiers, a.gap)

    print("[91%] 合并排名", flush=True)
    ranks = {w: rank(a.keyword, w, a.top, a.llm, not a.no_save, a.exclude) for w in a.windows}
    ranks = {w: ids for w, ids in ranks.items() if ids}
    if not ranks:
        print("[错误] 所有窗口都没出结果", flush=True)
        sys.exit(1)

    md = compare(a.keyword, ranks)
    if not a.no_save:
        slug = "+".join(a.keyword[:2])
        wins = "vs".join(f"近{w}天" for w in sorted(ranks))
        path = os.path.join(RESEARCH_DIR, f"{slug}-抖音-{wins}对照-{date.today().isoformat()}.md")
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(md)
        print(f"  对照表：{path}", flush=True)
    else:
        print(md)
    print("[100%] 完成", flush=True)


if __name__ == "__main__":
    main()
