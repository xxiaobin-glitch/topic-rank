# topic-rank

三平台（抖音 / B站 / 小红书）话题内容排行 Claude Code skill，附创作者 watchlist 监控。

## 功能

- `rank.py`：输入关键词，拉三平台排行，按综合价值 / 传播力 / 互动率评分，输出 Markdown 存档
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

将整个目录放到 `~/.claude/skills/topic-rank/`，Claude Code 会自动识别 `SKILL.md`。

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
