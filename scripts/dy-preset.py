#!/usr/bin/env python3
"""
管理 data/dy-presets.json 里预设榜单的排除名单（暂时学不了、榜里不看的作者）。

排除按 sec_uid（作者改昵称也对得上）；只作用于该预设的榜，watchlist 不受影响。

用法：
  python3 dy-preset.py list   [--preset ai剧情]
  python3 dy-preset.py add    --name 罗臣臣 --reason "3D动画做不了" [--preset ai剧情] [--sec-uid UID]
  python3 dy-preset.py remove --name 罗臣臣 [--preset ai剧情]

add 不给 --sec-uid 时，按昵称在近 7 天抓过的抖音数据里找；同名多人会列出来让你指定。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(os.path.dirname(HERE), "data", "dy-presets.json")
JSONL_DIR = os.path.expanduser("~/Projects/MediaCrawler/data/douyin/jsonl")


def load() -> dict:
    with open(PRESETS) as f:
        return json.load(f)


def save(d: dict) -> None:
    with open(PRESETS, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def find_uid(name: str) -> str:
    uids: dict[str, str] = {}
    for back in range(7):
        day = date.fromordinal(date.today().toordinal() - back).isoformat()
        path = os.path.join(JSONL_DIR, f"search_contents_{day}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("nickname") == name and r.get("sec_uid"):
                    uids[r["sec_uid"]] = r.get("title", "")[:30]
    if not uids:
        sys.exit(f"[错误] 近 7 天的抓取数据里没有「{name}」（要完整昵称），或用 --sec-uid 直接给")
    if len(uids) > 1:
        print(f"[错误] 「{name}」对应多个作者，用 --sec-uid 指定：")
        for u, t in uids.items():
            print(f"  {u}  例：{t}")
        sys.exit(1)
    return next(iter(uids))


def main():
    p = argparse.ArgumentParser(description="管理预设榜单的排除名单")
    p.add_argument("action", choices=["list", "add", "remove"])
    p.add_argument("--preset", default="ai剧情")
    p.add_argument("--name")
    p.add_argument("--sec-uid", dest="sec_uid")
    p.add_argument("--reason", default="")
    a = p.parse_args()

    d = load()
    if a.preset not in d:
        sys.exit(f"[错误] 没有预设「{a.preset}」，可选：{'、'.join(d)}")
    ex = d[a.preset].setdefault("exclude", [])

    if a.action == "list":
        print(f"「{a.preset}」排除名单（{len(ex)} 人）：")
        for e in ex:
            print(f"  {e['name']}  {e.get('reason', '')}  （{e.get('added', '')}）")
        return

    if not a.name:
        p.error("add/remove 需要 --name")

    if a.action == "add":
        if any(e["name"] == a.name for e in ex):
            sys.exit(f"「{a.name}」已在排除名单里")
        uid = a.sec_uid or find_uid(a.name)
        ex.append({"name": a.name, "sec_uid": uid, "reason": a.reason,
                   "added": date.today().isoformat()})
        save(d)
        print(f"已排除：{a.name}（{a.reason or '无原因'}）——之后「{a.preset}」榜不再出现他的视频")
    else:
        kept = [e for e in ex if e["name"] != a.name]
        if len(kept) == len(ex):
            sys.exit(f"[错误] 排除名单里没有「{a.name}」")
        d[a.preset]["exclude"] = kept
        save(d)
        print(f"已移出排除名单：{a.name}")


if __name__ == "__main__":
    main()
