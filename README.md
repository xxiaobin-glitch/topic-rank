# topic-rank

三平台（抖音 / B站 / 小红书）话题内容排行 Claude Code skill，附创作者 watchlist 监控。

## 功能

- `rank.py`：输入关键词，拉三平台排行，按综合价值 / 传播力 / 互动率评分，输出 Markdown 存档
- `dy-batch.py`：抖音多标签批量抓取（逐个抓防限流）→ 出多个时间窗口的榜 + 趋势对照表，用 `tools/progress/run-task` 启动可在菜单栏看进度
- `dy-preset.py`：管理预设榜单（`data/dy-presets.json`）的排除名单
- `watchlist.py`：监控 `data/watchlist.json` 里的创作者，拉抖音最新视频，按点赞排名

## 依赖

### Python 包

```bash
pip install pyyaml
```

### 外部工具

| 工具 | 用途 | 安装 |
|------|------|------|
| [opencli](https://github.com/OpenCLI-Project/opencli) | 抖音话题页抓取、创作者视频拉取 | 见官方文档 |
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | B站 / 小红书数据抓取 | 见官方文档 |

> opencli 建议装在独立 Chrome Profile，与主浏览器隔离。

## 安装

把整个目录放到任一 skill 目录即可，脚本内部不依赖安装位置（路径按自身实际位置推导）：

- **Claude Code**：`~/.claude/skills/topic-rank/`，会自动识别 `SKILL.md` 并按 description 触发。
- **跨平台共享**：`~/.agents/skills/topic-rank/`，Claude Code 侧建一个软链指过去即可；Codex 按路径读 `SKILL.md` + 直接跑脚本。

两处**只保留一份实体**，另一处用软链，避免两份分叉（2026-08-01 就分叉过一次，见 `notes/NEXT.md`）。

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOPIC_RANK_RESEARCH_DIR` | `~/topic-rank-research` | 排行存档目录 |
| `MEDIACRAWLER_DIR` | `~/Projects/MediaCrawler` | MediaCrawler 安装路径 |

示例：

```bash
export TOPIC_RANK_RESEARCH_DIR="~/Documents/你的目录"
export MEDIACRAWLER_DIR="~/your/path/to/MediaCrawler"
```

### watchlist

复制示例文件，填入创作者信息：

```bash
cp data/watchlist.example.json data/watchlist.json
```

`data/watchlist.json` 已在 `.gitignore` 中，不会提交到 git。

## 用法示例

```bash
# 三平台查「AI视频」
python3 scripts/rank.py "AI视频"

# 只查B站，传播力模式
python3 scripts/rank.py "seedance" --platforms bili --score virality

# 近 10 天内容
python3 scripts/rank.py "手机摄影" --within 10

# 查 watchlist 所有创作者
python3 scripts/watchlist.py

# 只查某人
python3 scripts/watchlist.py --name 编导李让
```

## 飞书通知

待日后实现。计划：运行后自动推送摘要到飞书群。

## 抖音抓取环境依赖（MediaCrawler）

抖音关键词排行走 MediaCrawler，浏览器启动分两级：

1. **CDP 模式**（优先）：用系统 Chrome 启动带调试端口的独立实例（profile: `browser_data/cdp_dy_user_data_dir`）
2. **标准 Playwright 模式**（CDP 失败时的 fallback）：用 Playwright 自带 Chromium（profile: `browser_data/dy_user_data_dir`）

**已知坑：**

- **Chrome 自动更新可能让 CDP 模式失效**（新版本收紧自动化启动限制），报错 `Server disconnected without sending a response`。fallback 到标准模式时如果没装过 Playwright 浏览器会接着报 `Executable doesn't exist`。
  → 解决：`cd ~/Projects/MediaCrawler && source .venv/bin/activate && playwright install chromium`（约 250MB，独立于系统 Chrome，装一次长期有效，直到 Playwright 版本升级）
- **profile 目录锁残留**：如果上次运行的浏览器进程被异常杀掉（比如后台任务被强制终止），`browser_data/*/SingletonLock` 不会被清理，下次运行会报 `Failed to create SingletonLock: File exists`。
  → `douyin-rank-custom.py` 的 `clear_stale_browser_locks()` 会在每次运行前自动检测并清理僵尸锁（只在确认没有进程占用该 profile 时才清），一般不需要手动处理。手动清理：`pkill -f dy_user_data_dir`
- **MediaCrawler 子进程输出必须被捕获**：`run_mediacrawler()` 用 `capture_output=True` 运行 MediaCrawler，不能让它的日志直接继承 stdout——否则 `rank.py` 会把这些日志原样存进最终的 Markdown 存档。这是历史踩过的坑，改动这块代码时要注意别退回去。
