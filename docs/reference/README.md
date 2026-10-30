# 信源台账（参考件，未接入流水线）

这里保留的是早期版本的机读信源配置：`sources.yaml`（37 个信源 + 8 类内容路由 + 授权标记）、`routes.json`（导出的路由，供非 Python 侧调用）、`source_registry.py`（加载与校验脚本）。

**当前生成流程不读取这些文件。** 一手域名的判定已内联到 `scripts/wr/collect.py`（`OFFICIAL_DOMAINS`），标的池、公告口径与下周日历统一放在 `config/weekly.yaml`，避免出现两套互相漂移的白名单。

保留原因：其中的分层策略（L1 法定披露 / L2 数据商 / L3 媒体 / L4 社交）、各源授权范围与断言集，仍是扩展采集通道时的参考依据。若后续要把付费数据源或港股公告通道接进来，以这份台账为起点补齐 `verified` 实测日期后再并入 `config/weekly.yaml`。
