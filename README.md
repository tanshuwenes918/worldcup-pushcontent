# Vanso 2026 世界杯 Push 内容生成器

赛事驱动的实时 Push 内容自动化系统，为 AI 音乐生成 App (Vanso) 在世界杯期间提供多语言 Push 文案和 AIGC Prompt。

## 快速开始

### 1. 安装依赖

```bash
cd "C:\Users\AS\Desktop\足球信息实时播报"
pip install -r requirements.txt
# 如果需要 X Trending 数据：
playwright install chromium
```

### 2. 配置

复制 `.env.example` 为 `.env`，填入你的 API 密钥：

```bash
cp .env.example .env
# 编辑 .env 填入 API_FOOTBALL_KEY, LLM_BASE_URL, LLM_API_KEY 等
```

### 3. 使用

```bash
# 比赛日自动管线：聚合数据赛程 + X Sports Trending + LLM 7 语言 + 飞书
python main.py matchday

# 本地验证：不访问外部 API / 不调用 LLM / 不写飞书
python main.py matchday --sample-data --mock-llm --dry-run

# 指定比赛日，限制处理 3 场
python main.py matchday --date 2026-06-18 --limit 3

# 生成 Push 内容（完整流程）
python main.py generate \
  --match "FRA vs BRA" \
  --event goal \
  --player "Vinícius Júnior" \
  --minute 78 \
  --score "1-2" \
  --stage "小组赛" \
  --venue "MetLife Stadium"

# 强制指定场景
python main.py generate \
  --match "MEX vs CAN" \
  --event var_controversy \
  --minute 89 \
  --scenario "主场狂热"

# DRY RUN（不写入 Bitable）
python main.py generate --match "ARG vs FRA" --event goal --player "Messi" --minute 90 --dry-run

# 测试模式（模拟数据）
python main.py test
```

## 事件类型

| 参数值 | 含义 | 默认场景 |
|--------|------|---------|
| `goal` | 进球 | 情怀致敬 |
| `red_card` | 红牌 | 玩梗群嘲 |
| `penalty` | 点球 | 玩梗群嘲 |
| `var_controversy` | VAR 争议 | 主场狂热 |
| `upset` | 爆冷 | 主场狂热 |
| `injury` | 伤退 | 遗憾怀念 |
| `hat_trick` | 帽子戏法 | 情怀致敬 |
| `own_goal` | 乌龙 | 玩梗群嘲 |
| `last_minute_goal` | 绝杀 | 情怀致敬 |
| `penalty_save` | 扑点 | 情怀致敬 |
| `milestone` | 里程碑 | 情怀致敬 |

## 项目结构

```
├── main.py                          # CLI 入口
├── config/settings.py               # 配置管理
├── data_sources/api_football.py     # API-Football 客户端
├── scrapers/x_trending_scraper.py   # X Trending 数据抓取
├── processors/
│   ├── scenario_classifier.py       # 事件→场景分类
│   ├── content_generator.py         # LLM 内容生成
│   └── translator.py               # 多语言文化适配
├── exporters/bitable_exporter.py    # 飞书 Bitable 写入
├── data/player_memes.json           # 球员梗标签库
└── outputs/                         # JSON 输出目录
```

## 数据源

- **聚合数据** (主): 官方赛程和球队信息
- **X Sports Trending** (辅): Playwright 抓取 Sports 分类，并按 48 队、世界杯关键词、球星名过滤

## 生成策略

GitHub Actions 每天 09:30（北京时间）触发一次，但内容不是按“每场比赛 1 条”生成，而是按 Push 触发机会生成：

- 每场比赛至少生成 1 条官方赛程机会，如赛前预热、实时赛况、赛后复盘。
- X Sports Trending 过滤后会按球队/世界杯关键词匹配到具体比赛，形成额外热点机会。
- 默认每场最多生成 `MATCHDAY_MAX_PUSHES_PER_MATCH=2` 条：1 条官方/赛况事实锚点 + 最多 1 条 X 热点角度。
- 因此每日写入飞书条数约为：当天比赛场数 × 1~2。当天没比赛则写入 0 条。

## GitHub 定时任务

`.github/workflows/matchday-push.yml` 会每天定时运行 `python main.py matchday`。需要在 GitHub Secrets 中配置：

`JUHE_API_KEY`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `FEISHU_BASE_TOKEN`, `FEISHU_TABLE_ID`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `X_COOKIES`。

本地仍可使用 `lark-cli` 写入飞书；GitHub Actions 推荐使用 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 直接调用飞书开放平台。

本地 `lark-cli` 会优先使用 `.env` 里的 `LARK_CLI_PATH`；如果留空，则自动从系统 `PATH` 查找 `lark-cli.cmd` 或 `lark-cli`。代码不依赖任何本机私有目录。

## 输出

- **飞书多维表格**: 自动生成记录，运营审核后可发布
- **JSON 文件**: 每次生成的完整数据存档

## 语言支持

EN / ZH / ES / MS / FIL / PT-PT / PT-BR (7 语言)
