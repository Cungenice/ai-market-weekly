# A/H AI Market Weekly

面向 A 股与港股的 AI、科技创新市场周报静态站点。每周一北京时间 09:30 自动生成，也可以在 GitHub Actions 中手动运行。

## 设计原则

1. **数字只有两种来源**：从一手来源原文抽取，或由代码计算。模型只负责语言，不生成数字。
2. **每条陈述都要有溯源**：一手来源编号（`source_ids`）、计算台账键（`metric_ids`）或日历规则（`basis`），三者至少有一个，否则校验不通过。
3. **事实闸门阻断、结构闸门降级**：数字对不上、禁语命中、免责缺失 → 不发布；素材不足 → 出精简版，而不是整期停更。
4. **落点是「透露了什么」而不是「发布了什么」**：正文不复述公告标题、不罗列名单；重点条目的第二问是「关注原因」，写这批信息为什么会走到台前，而不是再强调一次它重要。只写披露事实、没有任何解读的条目会被 `enforce_framing` 拦下重写。

## 工作流程

1. **四通道采集**（任一通道失败不影响其余）
   - 公告：按 `config/weekly.yaml` 的标的池逐只查询巨潮资讯网结构化接口，白名单公告类型，同一发行人同期多条合并为一条。
   - 行情：港交所每日统计页（主板成交额 + 恒生指数），逐日核验日期与章节后才入库。
   - 日历：统计局/海关/央行的发布窗口与法定披露截止日，规则推算，不依赖外部接口。
   - 线索：Google News 仅用于发现，链接必须解析到一手域名才可能进入正文。
2. **计算派生指标**：周涨跌、振幅、自高点回落、成交额环比等全部由 `scripts/wr/metrics.py` 计算，写入台账（ledger）。
3. **生成正文**：优先调用 DeepSeek（输入是台账 + 来源条目，禁止生成数字）；模型不可用或校验不过时，退回规则叙事（同样输出有判断的条目）。校验失败会带着错误回喂重写一次。
4. **三道校验**：结构 / 数字台账 / 合规，任一不过即阻断。
5. **渲染发布**：`index.html`、`weekly/<期号>.html`、`weekly/<期号>.json`、`data/archives.json`、`weekly/index.html`。

## 期次与节奏

- 期号按 ISO 周：`2026-W44`，区间为「上一个周一 09:30 → 生成时刻」。
- 周一 09:30 定时运行时区间恰为完整一周；周中补跑覆盖到当前时刻，页面标注「周内运行」。
- 同一期次重复运行覆盖同一份文件，不会新增目录项。
- 历史遗留的按日期命名的期次（`weekly/2026-10-27.html` 等）保留不动，仍可从目录访问。

## 运行

```bash
python -m pip install -r requirements.txt
python tests/test_gates.py                 # 闸门自测，不联网
python scripts/generate_weekly.py --dry-run --no-model   # 写到 preview/，只用规则叙事
python scripts/generate_weekly.py          # 正式生成
```

手动触发可选三种模式：

| 模式 | 行为 |
|---|---|
| `publish` | 生成 → 校验 → 提交 `main` → 部署 Pages |
| `preview` | 生成 → 校验 → 只上传 Actions artifact，不提交、不部署 |
| `deploy_only` | 跳过生成与提交，只用仓库现有文件重新部署 Pages |

## 一次性配置

1. **Settings → Secrets and variables → Actions** 新建 `DEEPSEEK_API_KEY`（不填也能跑，会退回规则叙事）。
2. **Settings → Pages → Build and deployment** 将 Source 设为 **GitHub Actions**。
3. **Settings → Actions → General → Workflow permissions** 允许 workflow 写入仓库内容。

## 文件

| 路径 | 作用 |
|---|---|
| `config/weekly.yaml` | 标的池、公告白/黑名单、下周日历、免责与禁语、校验阈值 |
| `scripts/generate_weekly.py` | 编排：采集 → 计算 → 生成 → 校验 → 渲染 |
| `scripts/wr/settings.py` | 配置加载、数值格式化、期次窗口 |
| `scripts/wr/collect.py` | 四通道采集 |
| `scripts/wr/metrics.py` | 派生指标与台账 |
| `scripts/wr/narrative.py` | 规则叙事（无模型时的兜底，也用于生成下周日历与上期回顾） |
| `scripts/wr/llm.py` | 模型接口与提示词 |
| `scripts/wr/validate.py` | 结构 / 数字 / 合规校验 |
| `scripts/wr/render.py` | SVG 图表与页面渲染 |
| `scripts/wr/assets/` | 样式与长图导出脚本 |
| `tests/test_gates.py` | 闸门自测 |

## 校准

- 新增标的：编辑 `config/weekly.yaml` 的 `stock_pool.a_share`（代码、名称、主题），主题用于成稿时的板块归并。
- 新增公告类型：在 `filings.categories` 增加一条（`match` 关键字 + `gloss` 口径说明），并在 `include_title_terms` 里放行。
- 新增日历事项：`calendar.known_events` 填具体日期；常规发布窗口改 `calendar.recurring`。
- 调整校验强度：`validation` 段的 `number_tolerance_abs` 控制数字比对容差；`require_disclosure_insight` 与 `insight_terms` 控制「只写披露事实」的条目是否放行。
- 调整写作口径：`filings.categories` 里每个类型的 `gloss` 是「这类公告透露什么」，`focus` 是「该看什么」，两者同时供模型参考与规则兜底使用。

## 数据与边界

- 公告只取标题与结构化元数据，**不解析 PDF 正文**，因此公告条目不含营收、净利等财务数值，统一标注「以公告原文为准」。要补这些数值需要引入 PDF 解析并逐字段校验，属于后续工作。
- 行情目前只覆盖港股主板成交额与恒生指数，A 股尚无自有指数/成交通道，因此 A 股部分只做公告层面的解读，不声称指数涨跌或全市场成交。
- 港交所页面结构或字段变化会导致当日行情被拒收，程序会记录并降级，不会用旧值顶替。
- Google News 解析依赖未公开接口，随时可能失效；失效时线索通道为空，不影响公告与行情通道。
