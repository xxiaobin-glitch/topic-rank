---
name: topic-rank
description: 查询某个话题/关键词在抖音、B站、小红书的内容排行表现。当用户说「查B站 X」「搜小红书 X」「三平台排行 X」「抖音热门 X」「X 在各平台表现怎么样」「帮我查查 X 相关内容」「X 哪些视频最火」时，务必触发此 skill，即使用户没有说"排行"这个词。当用户说「查 watchlist」「看一下我关注的人」「监控的创作者」「watchlist 更新了吗」时，路由到 watchlist 命令。
---

# topic-rank

根据用户给出的话题关键词，查询该话题在各平台的内容排行，帮助判断内容方向和选题价值。

## 脚本位置

```
~/.claude/skills/topic-rank/scripts/
```

## 执行命令

**话题排行（三平台）：**
```
python3 ~/.claude/skills/topic-rank/scripts/rank.py <keyword> [参数]
```

**创作者 watchlist：**
```
python3 ~/.claude/skills/topic-rank/scripts/watchlist.py [参数]
```

## 参数映射 — 话题排行

**平台**（`--platforms`，默认三个全查）：

| 用户说的 | 参数 |
|---------|------|
| 抖音 / dy | `--platforms dy` |
| B站 / bilibili | `--platforms bili` |
| 小红书 / xhs | `--platforms xhs` |
| 没提平台 | 不加此参数（三个全查） |
| 两个平台 | 如 `--platforms dy xhs` |

**评分模式**（`--score`，默认 `value`）：

| 用户说的 | 参数 |
|---------|------|
| 爆款、传播、刷屏、最火 | `--score virality` |
| 互动、评论多、热度高 | `--score engagement` |
| 没提，或说"综合" | `--score value`（默认） |

**其他参数**：

| 用户说的 | 参数 |
|---------|------|
| 历史最高、有史以来、不限时间 | `--no-time-weight` |
| 近 N 天、最近 N 天、近期 | `--within N` |
| 只看 Top 5 / Top 20 等 | `--top N` |
| 只看看，不存、不保存 | `--no-save` |
| 值不值得做、要不要做、还知不知道接着做、要不要继续、判断一下、研究一下选题 | `--compare` |
| 和 AI 相关的、AI 做的、AI 制作 | `--require ai` |
| 和电影相关的、电影感 | `--require 电影` |
| 和爱情相关的 | `--require 爱情` |
| 和搞笑相关的 | `--require 搞笑` |
| 同时满足多个领域，如"AI 做的电影感" | `--require ai 电影` |

`--require` 说明：在抓回来的结果里二次过滤，只保留标题含指定词的视频。`ai` 会自动展开为完整 AI 工具词组（即梦、可灵、Seedance、AIGC 等），其他词如「电影」也会展开为同义词（电影感、影视、cinematic 等）。多个词之间是 AND 逻辑（每个词都要满足）。

`--compare` 触发1天+7天联查，自动生成对比分析，帮助做选题决策。不指定 `--within` 时使用此模式。

存档默认存到 `~/topic-rank-research/`。若想改存档目录，设置环境变量 `TOPIC_RANK_RESEARCH_DIR`。

## 参数映射 — watchlist

| 用户说的 | 参数 |
|---------|------|
| 没提特别要求 | 直接运行（最近 20 条，Top 5） |
| 拉多一点 / 最近 30 条 | `--limit 30` |
| 看 Top 10 | `--top 10` |
| 只看某人，如「只查李让」 | `--name 编导李让` |
| 只看某个赛道，如「只看爽文类」 | `--category "爽文·反道德绑架"` |
| 有哪些分类 / 分了几个类 | `--list-categories` |
| 把某人加进 watchlist | `--add --name "名字" --sec-uid <uid> --category "分类名" [--note "备注"]` |

## 执行步骤

1. 从用户话里提取关键词和意图，按上面的映射表构建命令
2. 用 Bash 运行命令
3. 把脚本输出直接呈现给用户（输出已经足够清晰，不需要二次整理）
4. 如果存了档，告诉用户文件保存在哪里

遇到模糊的情况，先按最合理的参数跑，跑完再问要不要调整，不要跑之前反复确认。

## 示例

**查单平台：**
用户：「查B站 seedance」
```bash
python3 ~/.claude/skills/topic-rank/scripts/rank.py "seedance" --platforms bili
```

**查三平台：**
用户：「三平台看看 AI视频 最近表现」
```bash
python3 ~/.claude/skills/topic-rank/scripts/rank.py "AI视频"
```

**近期时间窗口：**
用户：「查一下近 10 天 AI视频 的热榜」
```bash
python3 ~/.claude/skills/topic-rank/scripts/rank.py "AI视频" --within 10
```

**指定模式：**
用户：「小红书手机摄影历史最火的，看传播力」
```bash
python3 ~/.claude/skills/topic-rank/scripts/rank.py "手机摄影" --platforms xhs --no-time-weight --score virality
```

**多关键词合并（覆盖不挂标签的创作者）：**
用户：「查抖音 AI短片 和 ai创作浪潮计划 近7天」
```bash
python3 ~/.claude/skills/topic-rank/scripts/rank.py "AI短片" "ai创作浪潮计划" --platforms dy --within 7
```

**选题决策联查：**
用户：「拒绝道德绑架相关，看看还知不知道接着做」
```bash
python3 ~/.claude/skills/topic-rank/scripts/rank.py "拒绝道德绑架" "末世先杀圣母" --platforms dy --compare
```

**watchlist：**
用户：「查一下 watchlist」
```bash
python3 ~/.claude/skills/topic-rank/scripts/watchlist.py
```

用户：「只看李让，多拉一点」
```bash
python3 ~/.claude/skills/topic-rank/scripts/watchlist.py --name 编导李让 --limit 30
```
