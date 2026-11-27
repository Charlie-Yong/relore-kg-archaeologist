# ItsDangerous v2 期末增强实证评测汇总（2026-11-26）

本目录收录 **HistoryKG v2** 围绕可扩展性、时序增量演化、决定抽取去噪与盲测、问答延迟-准确率 Pareto 前沿、Codex CLI 通用 Agent 双口径审计、8 道未见题盲测、第二仓库零改造迁移与 `v7` 便携冷启动复演的全部机器可读产物与可复现脚本。

> **口径与版本隔离铁律**：本目录验证主基线为 `pallets/itsdangerous`（冻结于 `2026-11-16T06:31:18Z`，`672971d66a2ef9f85151e53283113f33d642dabd`，`dataset:0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2`）与第二仓库 `pallets-eco/blinker`（`dataset:ea5bc3a05942f191c9fb23f8eb268e15b50b5e70946202b8d2052c1b6170f4d4`）；`2026-10-30` Flask 正式实验与 `2026-11-21` ItsDangerous v1/v6 基线（[qa-summary.json](../itsdangerous-final-20261121/qa-summary.json)）均独立保留，跨版本实体数与指标严禁相加或混写。详细解读见 [期末技术报告](../../reports/itsdangerous_final.md)。

---

## 一、实验产物与脚本索引

| 类别 | 文件 | 核心内容 |
| --- | --- | --- |
| 扩展性基准脚本 / 结果 | [bench_scaling.py](bench_scaling.py) · [scaling-benchmark.json](scaling-benchmark.json) | Neo4j 5.26 下 `1x` / `5x` / `10x` 克隆压测（`snapshot` vs `cypher_subgraph` 延迟与 `1x` 路径等价性） |
| 时序增量脚本 / 结果 | [eval_incremental.py](eval_incremental.py) · [incremental-summary.json](incremental-summary.json) | `T1(<=2018-10-31) → T2(<=2021-05-31) → T3(全历史)` 增量 `apply_delta` 等价性与时间探针 |
| 抽取对比脚本 / 结果 / 逐条审计 | [eval_extraction_v2.py](eval_extraction_v2.py) · [extraction-v2-summary.json](extraction-v2-summary.json) · [extraction-v2-audit.json](extraction-v2-audit.json) | `PROMPT_V1` vs `PROMPT_V2` 在 `orig30` 与不相交 `heldout20` 上的双数据集评测（`glm-5.3` 异构裁判） |
| 问答对比脚本 / Pareto / 未见盲测 | [eval_qa_v2.py](eval_qa_v2.py) · [qa-pareto-summary.json](qa-pareto-summary.json) · [qa-unseen-summary.json](qa-unseen-summary.json) | 公共 6 题 Pareto 寻优、Codex CLI `E` 组双口径审计、`U1–U8` 密封盲测 |
| 跨仓迁移脚本 / 结果 | [eval_second_repo.py](eval_second_repo.py) · [blinker-generalization.json](blinker-generalization.json) | `pallets-eco/blinker` 零代码修改端到端建图、GraphQL `Closes` 捕获与 `BL1–BL6` 问答对照 |
| 预算护栏与冷启动复演收据 | [budget_guard.py](budget_guard.py) · [portable-rehearsal-v7.json](portable-rehearsal-v7.json) | 15.0 CNY 硬上限守卫与 `v7` 解包冷启动实测收据（Neo4j 导入、离线回放、6 题实时快问） |

---

## 二、已核实关键指标摘要

1. **图谱规模扩展性（[scaling-benchmark.json](scaling-benchmark.json)）**
   - `1x`（4,067 实体 / 11,674 关系 / 7,417 来源 / 14,897 证据）：`snapshot` P50 `2107.36 ms`（P95 `2664.30 ms`）vs `cypher_subgraph` P50 `556.16 ms`（P95 `799.45 ms`），P50 提速 **3.79x**（P95 **3.33x**）；6 类代表性查询路径数量 `paths_equal=True` 达 6/6，Top 候选 `top_candidates_equal=True` 达 4/6（`change`/`timeline` 因平局排序略有差异）。
   - `5x`（20,335 实体 / 58,370 关系 / 37,085 来源）：`snapshot` P50 `11615.32 ms`（P95 `14573.39 ms`）vs `cypher_subgraph` P50 `2082.47 ms`（P95 `3426.92 ms`），P50 提速 **5.58x**（P95 **4.25x**）。
   - `10x`（40,670 实体 / 116,740 关系 / 74,170 来源 / 148,970 证据）：`snapshot` P50 `23515.64 ms`（P95 `31421.50 ms`）vs `cypher_subgraph` P50 `3015.58 ms`（P95 `6324.91 ms`），P50 提速 **7.80x**（P95 **4.97x**）。
2. **时序增量演化与等价性（[incremental-summary.json](incremental-summary.json)）**
   - `T1 (<=2018-10-31)`：2,528 来源 / 1,741 实体 / 3,375 关系（写入 `4532.38 ms`；`slice_package` 通过 Commit/Tag 日期映射、Issue/PR `created_at` 及仓库级 JSON 列表逐条目截断，彻底消除无 `occurred_at` 未来来源泄漏，三项探针 `has_pr152=false`、`has_220_release=false`、`has_pr372=false`）。
   - `T2 (<=2021-05-31)`：4,807 来源 / 2,861 实体 / 7,053 关系，增量 upsert `2,286` 来源 / `1,122` 实体 / `3,678` 关系（`delta_ms=1721.71 ms`；`q_simplejson_pr152` 从 `has_pr152: false` 切换为 `true`，`2.2.0` 与 `PR #372` 仍保持 `false`）。
   - `T3 (2026-11-16)`：7,417 来源 / 4,067 实体 / 11,674 关系，增量 upsert `2,614` 来源 / `1,209` 实体 / `4,621` 关系（`delta_ms=2604.35 ms` vs 从头重建 `full_rebuild_ms=3088.00 ms`，提速 **1.19x**；三项探针均切换为 `true`，且全库 `fingerprint_equal=true` 及全部对象计数严格相等）。
3. **决定抽取 `PROMPT_V1 → PROMPT_V2`（[extraction-v2-summary.json](extraction-v2-summary.json)）**
   - **`orig30`（30 单元 / 18 金标 / 17 理由需核）**：`v1` 为 `10 TP / 15 FP / 8 FN`，Precision `0.4000` `[0.2340, 0.5926]`、Recall `0.5556` `[0.3372, 0.7544]`、F1 `0.4651`、理由覆盖 `5/17 = 0.2941` `[0.1328, 0.5313]`、`bot_bump=8`；`v2` 提升为 `10 TP / 5 FP / 8 FN`，Precision **`0.6667`** `[0.4171, 0.8482]`、Recall `0.5556` `[0.3372, 0.7544]`、F1 **`0.6061`**、理由覆盖 `9/17 = 0.5294` `[0.3096, 0.7383]`、`bot_bump=0`。
   - **`heldout20`（不相交 20 单元 / `14` 已解析参考 + `1` 条 `unresolved_references`）**：严格按 `reference_complete=False` 口径将汇总字段 `precision` / `recall` / `f1` / `rationale_coverage` 保留为 `null`；已解析条件计数下，`v1` 为 `9 TP / 8 FP / 5 FN`（条件 Precision `52.9%` `[0.3096, 0.7383]`，理由覆盖 `3/8`，`bot_bump=6`），`v2` 提升为 `9 TP / 3 FP / 5 FN`（条件 Precision **`75.0%`** `[0.4677, 0.9111]`，理由覆盖 `5/8`，`bot_bump=0`）。
   - **诚实边界**：长讨论隐含提案/维持现状结论仍有漏抽天花板（FN 分别为 8 和 5），且 30/20 小样本下 95% Wilson 置信区间存在重叠。
4. **问答 Pareto 前沿、Codex CLI `E` 审计与未见 8 题盲测（[qa-pareto-summary.json](qa-pareto-summary.json)、[qa-unseen-summary.json](qa-unseen-summary.json)）**
   - **公共 6 题 Pareto 最优 `B_v2_fast_nothink`**：显式配置 `reasoning_effort="none"` 后达成 **`17/17`（100%）**，中位单题延迟 **`3.40 s`**，271 条引文 100% 逐字匹配（对比 `B_v2_fast_low` `17/17` @ `7.64 s`、`B_v1` `14/17` @ `41.7 s`、`D` `17/17` @ `154.6 s`、`A_v1` `9.5/17` @ `25.2 s`、`O` `2/17` @ `13.3 s`）。
   - **Codex CLI `E` 双口径公平审计**：全部 6 题端到端得 **`10.5/17`（61.76%）**，中位 **`230.07 s`**（Q1/Q5 因 `::browser-complete` 工具封装字符串覆盖正文得 0 分）；剔除框架封装故障后，有效自然语言 4 题（Q3/Q7/Q9/Q11）得 **`10.5/11`（95.45%）**，中位 **`262.6 s`**，单题消耗 **`1.496M–4.426M` input tokens** 与 `12,688–37,593` output tokens。
   - **全新密封 8 题 `U1–U8`（满分 22）**：同模型下，纯文本检索 `A_v2` 得 `14.0/22`（63.64%，`2.71 s`，14 条引文）；`B_v2_fast` 得 **`20/22`（90.91%，+27.3pp，`2.98 s`，370 条引文）**；`B_v2_deep` 得 `19.5/22`（88.64%，`9.66 s`，379 条引文）。在 `U2`（拒收加密载荷与替代建议）`B_v2_fast` `3/3` vs `A_v2` `0/3`；在 `U6`（PR #373 最早正式版，分支 tag `2.1.x` vs 正式版 `2.2.0`）双方均仅得 `1/3` 或 `1.5/3`。
5. **第二仓库零代码改造迁移 `pallets-eco/blinker`（[blinker-generalization.json](blinker-generalization.json)）**
   - 未改动 `historykg/` 或 `app/` 业务代码直接端到端建图，`validation_status="ok"`，产出 **3,396 实体**（`Commit=317, Decision=151, Developer=44, File=578, Function=2097, Issue=54, Project=1, PullRequest=137, Release=17`）与 **5,958 关系**（真实捕获 GitHub GraphQL **`Closes=5`**，另有 `ClaimsToClose=5, MergedAs=87, ReachableIn=2368, Touches=281`）。
   - 跨仓 6 题问答（满分 13）：`B_v2_fast` 达 **`12/13`（92.31%，中位 `1.48 s`，277 条引文）**，对比 `A_v2` **`9/13`（69.23%，中位 `3.06 s`，19 条引文）**；其中 `BL2`（`Issue <-[Closes]- PR -[MergedAs]-> Commit -[Touches]-> File`）`B_v2_fast` 满分 `3/3`、`A_v2` `0/3`，`BL3` 跨版本标签判定均得 `1/2`。
6. **`v7` 便携冷启动实机复演与实际经费（[portable-rehearsal-v7.json](portable-rehearsal-v7.json)）**
   - 从 `v7` 候选包解压后在干净隔离 Neo4j 上导入耗时 `7.143 s`（7,417 来源 / 4,067 实体 / 11,674 关系 / 14,897 证据），离线回放 6 题 100% 通过逐字校验，6 题实时快问中位 **`3.385 s`**（`Q1: 2.38s` – `Q5: 4.60s`，`reasoning_tokens=0`），花费 `0.055832 CNY`。
   - Phase 2 实验共享账本（435 次调用）实支 `7.261228 CNY`，加上 `v7` 冷启动复演 `0.055832 CNY`，总支出 **`7.317060 CNY`**（严格低于 `15.0 CNY` 上限）。
