# 全球AI热点雷达 · Global AI Trend Radar

实时扫描全球 AI 热点，自动抓取并**翻译中文化**，按热度算法排序，支持话题过滤与中英文搜索的全栈应用。

## 技术栈

- **后端**: FastAPI + SQLite（单进程同时托管 API 与静态前端）
- **前端**: 原生 JS SPA + DESIGN·TANG 设计系统（暗黑主题 / 荧光绿 accent / 弹簧动画 / a11y baseline）
- **数据源**: Hacker News (Algolia) / Reddit / 12 路 RSS / GitHub Trending / 种子库兜底
- **中文化**: 抓取到的英文内容经 Google Translate（MyMemory 备源）自动翻译为中文，原文保留在 `original_title` / `original_summary`，卡片展开可看英文原句
- **热度算法**: `Score = (log10(views+1) + 0.5·log10(engagement+1)) × exp(-hours/72) + DomainWeight`

## 目录

| 文件 | 职责 |
|------|------|
| `app.py` | FastAPI 主应用：生命周期、API 路由、刷新/翻译编排 |
| `db.py` | SQLite 初始化 + CRUD + 原文列迁移 + 翻译持久化 |
| `scraper.py` | 多源并行抓取（HN/Reddit/RSS/GitHub） |
| `scorer.py` | 热度打分 + 等级（🔥🔴🟠🟡🟢） |
| `translator.py` | 英文→中文自动翻译（并发限流 + 缓存 + 降级） |
| `seed_data.py` | 100 篇兜底种子数据 |
| `templates/index.html` · `static/` | DESIGN·TANG 前端 |

## 本地运行

```bash
pip install -r requirements.txt
python app.py          # 默认 http://0.0.0.0:8787
```

## API

- `GET  /api/articles?category=&tag=&q=&sort=hot|time|views&limit=200` — 列表（中英文搜索）
- `GET  /api/articles/{id}` — 详情（含英文原文）
- `GET  /api/stats` — 统计（总数 / 已中文化篇数 / 分类）
- `POST /api/refresh` — 触发抓取刷新（新英文自动翻译）
- `POST /api/translate` — 回填历史英文文章翻译
- `GET  /api/health` — 健康检查

部署于 Render.com（`render.yaml`）。
