# A/H AI Market Weekly

面向 A 股与港股的 AI、科技创新市场周报静态站点。每周一北京时间 09:30 自动生成，也可以在 GitHub Actions 中手动运行。

## 工作流程

1. GitHub Actions 用 Google News RSS 发现最近 7 天的官方来源线索；RSS 不作为报告证据，程序会解析并只保留能直达交易所、监管机构或上市公司官网的链接。
2. 按二级市场信号优先级筛选直达来源，再由 DeepSeek 根据可见标题与摘要生成 A/H 市场观察；报告必须区分市场表现数据与事件线索，未提供的数字不得推算或补写。
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

重点动态优先考虑指数、成交、资金、融资融券、回购/增减持、解禁与交易异动等二级市场信号，再考虑上市公司业绩、订单和资本行动；ETF/基金例行季报降权。无法解析到官方直达来源的 Google News 中转链接会被丢弃。合格条目不足时少于 6 条，并做相似事件去重。

## 文件

- `index.html`：最新周报。
- `weekly/index.html`：历史周报目录。
- `weekly/`：按期次保存的静态 HTML。
- `scripts/generate_weekly.py`：新闻采集、摘要生成和静态页构建。
- `.github/workflows/market-weekly.yml`：定时/手动生成与 Pages 部署。

## 数据与边界

Google News RSS 只作发现入口；生成器会尝试解析链接，并严格丢弃无法解析到交易所、监管机构或上市公司官网的条目。它仍以官方页面可见的标题和摘要为输入，尚未抓取并核验公告全文。筛选排序偏向二级市场信号，例行 ETF/基金季报不会再占据重点版面。

当前版本尚未接入一套可持续、免费的 A 股和港股周度指数/成交/市场宽度数据接口。因此，报告不会声称提供完整的指数周涨跌、全市场成交或南向资金周度统计；若本期没有官方数据线索，页面应明确限定为事件观察，不能把公司公告摘要包装成市场表现。港交所部分逐日行情及沪港通历史数据在官方数据目录中属于订阅产品，后续如需完整量化周报，需要另行确定可合法使用的数据授权或公开统计来源。

