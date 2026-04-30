# 每日科技早餐简报 ☕

每天早上 9:00 自动生成并推送最新科技新闻简报，中英双语精选。

## 技术栈

- **Python** (`generate_briefing.py`) — 自动从 RSS 抓取新闻、提取摘要、渲染 HTML
- **GitHub Actions** — 每天定时运行、自动部署
- **GitHub Pages** — 免费托管，一键访问

## 文件结构

```
.
├── index.html              # GitHub Pages 入口（自动生成）
├── tech-briefing.html      # 简报页面（核心文件）
├── generate_briefing.py    # 新闻抓取脚本
└── .github/workflows/
    └── daily-briefing.yml  # 自动化工作流
```

## RSS 数据源

| 源 | 语言 |
|---|---|
| ArsTechnica | 🇺🇸 English |
| Solidot | 🇨🇳 中文 |
| Hacker News | 🇺🇸 English |

## 手动触发

在 GitHub 仓库 → **Actions** → **每日科技早餐简报** → **Run workflow** 即可手动刷新。
