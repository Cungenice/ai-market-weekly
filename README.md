# A/H AI Market Weekly

面向 A 股与港股的 AI、科技创新市场周报静态站点。每周一北京时间 09:30 自动生成，也可以在 GitHub Actions 中手动运行。

## 工作流程

1. GitHub Actions 查询 Google News RSS 中的 A 股、港股、AI/科技创新及市场主题资讯，时间窗口为最近 7 天。
2. DeepSeek Chat Completions API 根据标题、摘要和来源链接整理中文周报。报告区分 A 股与港股，突出 AI/科技创新，并列出来源。
3. 更新主页 `index.html`、历史期次 `weekly/YYYY-MM-DD.html`、目录 `weekly/index.html` 和 `data/archives.json`。
4. 将变更提交至 `main`，并在同一 workflow run 中部署 GitHub Pages。

报告由模型依据公开新闻标题和摘要自动整理。页面明确提示读者查看原文核实；不生成个股买卖建议，也不把预测包装成事实。

## 一次性配置

1. 在仓库 **Settings → Secrets and variables → Actions** 新建 repository secret：
   - `DEEPSEEK_API_KEY`：DeepSeek API key。请在 GitHub 页面填写，不要提交到仓库或贴到聊天里。
2. 在仓库 **Settings → Pages → Build and deployment** 将 Source 设为 **GitHub Actions**。
3. 检查 **Settings → Actions → General → Workflow permissions** 允许 workflow 写入仓库内容（`GITHUB_TOKEN` contents: write）。

仓库是公开的；任何人都能查看代码和已发布的周报。GitHub Pages 页面也会公开发布。

## 运行

- 自动：每周一 01:30 UTC（北京时间 09:30）。
- 手动：**Actions → A/H AI Market Weekly → Run workflow**。
- 手动触发可选择 `publish`（写入归档并部署）或 `preview`（只生成 Actions artifact，不提交、不发布）。
- 默认模型为 `deepseek-flash`；可在 workflow 的 `DEEPSEEK_MODEL` 环境变量中调整。

生成流程对每个周报期次幂等：同一归档日期重新运行会覆盖该期，不重复添加目录项。

## 文件

- `index.html`：最新周报。
- `weekly/index.html`：历史周报目录。
- `weekly/`：按期次保存的静态 HTML。
- `scripts/generate_weekly.py`：新闻采集、摘要生成和静态页构建。
- `.github/workflows/market-weekly.yml`：定时/手动生成与 Pages 部署。

## 数据与边界

新闻由 Google News RSS 搜索结果聚合；页面保留新闻来源、发布时间和原文链接。RSS 标题/摘要可能不完整，站点会明确标注自动整理及核验限制。该页面只作信息整理，不构成投资建议。市场指数实时行情暂不自动抓取，以免引入未经配置授权和核验的行情数据源。

