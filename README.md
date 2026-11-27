# 开源项目历史知识图谱与可追溯问答（HistoryKG）

输入公开 GitHub Python 仓库链接，**HistoryKG** 在**不执行目标仓库任何代码**的前提下（仅做只读 Git 历史与 `git diff-tree` 解析、Python `ast` 静态语法分析及只读 GitHub REST/GraphQL 采集），自动构建融合演化关系与设计决定的显式知识图谱（Neo4j 5.26 + SQLite FTS5），并通过 **Cypher 按需局部子图检索**回答带逐字字节级偏移出处的考古问题。

---

## 现行期末主线：HistoryKG v2（2026-11-26 ItsDangerous 增强版 / v7 复核候选）

为全面落实课程要求并直接回应 11 月 11 日期中课堂追问，期末交付已统一基于 **`pallets/itsdangerous`**（冻结于 `2026-11-16T06:31:18Z`，默认分支提交 `672971d66a2ef9f85151e53283113f33d642dabd`，`dataset:0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2`）完成 v2 工程升级与独立跨仓盲测，形成可离线冷启动复核的 **`v7` 课程候选提交包**（位于 `submission/HistoryKG-ItsDangerous-期末复核候选-v7.zip`，30 MB，174 项已校验成员，通过隐私与零绝对路径检查）。

### 交付文档与答辩入口

- **技术报告**：[期末技术报告 (Markdown)](reports/itsdangerous_final.md)（8,482 纯中文正文） · [期末技术报告 (PDF，16 页)](output/pdf/ItsDangerous-技术报告.pdf)
- **答辩与现场演示**：[12 页期末汇报 PPT](demo/final/ItsDangerous-期末汇报.pptx) · [演示操作与 5 分钟讲稿](demo/final/ItsDangerous-操作与讲稿.md) · [答辩追问 10 题应答小抄](demo/final/答辩追问应答小抄.md) · [便携演示配置](demo/final/itsdangerous.example.json) · [无编号问题 A/B 原文对照](demo/final/decision-ab-samples.md)
- **v2 评测与模块文档**：[v2 实验汇总索引](evaluation/itsdangerous-v2-20261126/README.md) · [图谱存储与按需查询](docs/graph_query.md) · [模型通道与抽取规范](docs/p4/models.md) · [工作台原型与回放说明](docs/p5/README.md) · [课程要求与改进核对](deliveries/review/2026-11-20-课程要求与期末改进清单.md)

### 核心实证成果与诚实边界

| 评估维度 | 核心实测数据 | 关键结论与诚实披露 |
| --- | --- | --- |
| **问答准确率与延迟 Pareto 前沿** | 默认 `B_v2_fast_nothink`（`cypher_subgraph` + `reasoning_effort="none"`）公共 6 题 **`17/17`（100%）**，中位 **`3.40s`**，271 条引文 100% 逐字匹配 | 比原版 `B_v1`（`41.7s` / 82.4%）快 **12.3x**，比双证据重推理 `D` 组（`154.6s` / 100%）快 **45.5x** |
| **通用 Coding Agent（Codex CLI `E` 组）双口径审计** | 全部 6 题端到端 `10.5/17`（61.8%，中位 `230.1s`）；有效自然语言 4 题 **`10.5/11`（95.5%）**，中位 **`262.6s`**，单题 **`1.50M–4.43M` 输入词元** | 不贬低强通用 Agent 的正常作答精度，但指出其高延迟、百万级 token 开销及工具封装/网页超时风险使其难以胜任课堂 3 秒级追问 |
| **8 道全新密封未见题（`U1–U8`，满分 22）** | 同模型纯文本 `A_v2` `14.0/22`（63.6%，`2.71s`，14 引文）vs 图谱快问 `B_v2_fast` **`20.0/22`（90.9%，+27.3pp，`2.98s`，370 引文）** | `U2` 拒收决定与替代建议 `B_v2_fast` 3/3 vs `A_v2` 0/3；`U6` 因 `2.1.x` 分支标签与 `2.2.0` 正式 Release 区分边界双方仅得 1/3–1.5/3 |
| **决定抽取 `PROMPT_V1 → PROMPT_V2`（双数据集）** | `orig30`（18 金标）：P `40.0% → 66.7%`、F1 `0.4651 → 0.6061`、理由覆盖 `29.4% → 52.9%`、**Bot `8 → 0`**；不相交 `heldout20`（14 已解析*）：条件 P `52.9% → 75.0%`、理由 `3/8 → 5/8`、**Bot `6 → 0`** | `heldout20` 含 1 条未决跨仓参考（`reference_complete=False`），总表严格保留 `null` 不凑整；如实承认 FN（8 与 5）召回天花板与小样本区间重叠 |
| **1x → 10x 图谱扩展性与时序增量** | `10x`（40,670 实体 / 116,740 关系 / 74,170 来源）：`cypher_subgraph` `3.02s` vs `snapshot` `23.52s`（P50 提速 **7.80x**）；`T1→T2→T3` `apply_delta` `1.68s` vs 全量重建 `2.66s`（**1.59x**） | `1x` 6/6 路径数严格一致，`T3` 全库指纹 `fingerprint_equal=true`；同期诚实记录 `/releases` 聚合接口缺少单条目时间过滤字段 |
| **第二仓库零代码改造迁移（`pallets-eco/blinker`）** | 一行源码不改产出 **3,396 实体 / 5,958 关系**，首次真实捕获 GraphQL **`Closes=5`**；`B_v2_fast` 跨仓问答 **`12/13`（92.3%，中位 `1.48s`）** vs `A_v2` `9/13`（69.2%） | 已清除 `historykg/` 全部 `simplejson` 硬编码；`BL2` 拿满分 3/3（纯文本 0/3），`BL3` 复现与 `U6` 一致的跨版本标签边界（1/2） |
| **便携冷启动实机复演与全库检验** | 干净 Neo4j 导入 `7.143s`、离线回放 6/6 逐字通过、6 题实时快问中位 **`3.385s`**、`pytest` `178 passed` + Neo4j `41 passed` + 回归 `39 passed`、规划/隐私 `0` 错 | 全部 Phase 2（435 次调用，`7.2612 元`）加冷启动复演（`0.0558 元`）合计支出 **`7.3171 元`**（远低于 15.0 元预算上限） |

### 快速启动（便携实机演示 / 离线兜底 / 新建任意公开仓库）

1. **从课程候选包启动现场便携可提问工作台**（macOS / Linux，已启用 `.streamlit/config.toml` 无 Deploy 极简外观，内置快速实证 / 深度思考开关与 4 枚一键场景按钮）：

~~~sh
# 先启动 Neo4j 5.26（bolt://127.0.0.1:7687），并从发布包根目录运行：
PYTHONPATH=source .venv/bin/python -m tools.serve_frozen frozen \
  --config materials/itsdangerous.example.json --port 8517
~~~

   在源码仓直接验证 `.local` 冻结包时（Neo4j 按实际服务端口配置于便携 JSON 中）：

~~~sh
.venv/bin/python -m tools.serve_frozen \
  .local/full-history-itsdangerous/datasets/dataset-0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2 \
  --config demo/final/itsdangerous.example.json --port 8517
~~~

2. **断网或 API 波动时的零等待离线回放兜底**：

~~~sh
HISTORYKG_REPLAY_FILE=materials/itsdangerous-replay.json \
  PYTHONPATH=source .venv/bin/streamlit run source/app/main.py --server.address 127.0.0.1 --server.port 8517
~~~

3. **运行自动化验收与隐私合规检查**：

~~~sh
.venv/bin/python -m pytest -q
.venv/bin/python tools/check_planning.py
.venv/bin/python tools/check_public_privacy.py --tracked
~~~

---

## 历史归档与早期工程基线（版本独立，勿跨版混用）

> **版本边界声明**：下方内容保留 **2026-10-30 Flask 正式包**（369 来源、133 实体、183 关系、旧版全量检索基线）、**11 月 8 日–11 日期中材料**以及早期 Windows/PostgreSQL 开发规划说明，供工程追溯。其实体数、关系数与分数仅适用于对应历史基线，**严禁与上文 2026-11-26 ItsDangerous v2 / Blinker 期末数据相加或混淆**。

期中课堂展示归档：[科研架构详解版](demo/midterm/期中汇报_科研架构详解版_20261108_完整版.pptx) · [PDF 放映备用](output/pdf/期中汇报_科研架构详解版_20261108_完整版.pdf) · [详细讲解手册](demo/midterm/科研架构详解_讲解手册.md) · [简版课件](demo/midterm/期中汇报_原理流程版_20261108.pptx)。

本仓库已按用户授权公开，规划可直接阅读；提交和管理仍按实际授权。密钥、私有测试参考和个人实名材料（成员姓名、11 位学号、分工确认与组内互评）不在公开仓库中保存。

**已归档的 Flask 实验（2026-10-30，旧版检索）：** URL 自动流水线、真实 LLM 抽取、Neo4j 与同源检索、统一问答接口、Streamlit 原型及正式实验汇总已接通。默认 Flask URL 作业已完成全部六阶段并发布 ready，冻结 369 来源、40 个完整讨论单元和 24 个源码快照，产出 133 个业务实体、183 条关系、333 份证据，其中 61 个 Decision 已包含在实体总数中。P3 只读增量分片另生成 18 Developer、384 Function、20 Authored、4 Merged、384 Defines 及 508 条证据，并核对 PR #6096 到 `flask.testing._get_werkzeug_version` 的固定链。40 个生产抽取 run 共 42 次实际尝试，含重试；30 个测试线程的抽取 P/R/F1 为 0.568/0.962/0.714。24 道题保存 48 个 A/B 答案并由 24 次匿名评审覆盖，测试事实覆盖 A/B 为 0.600/0.740，配对差 0.157 但 95% 描述性 bootstrap 区间跨零。全池首轮 6 个失败位置经一次格式恢复重试后为 92/92，6 道候选均完成两遍核验；确认证据不足 0，正确弃答率 N/A 仅因合格分母 0。第二小库测试 `pallets/itsdangerous`（10-30 早期小样本版）生成 347 来源、30 完整讨论、17 文件快照、82 实体、78 关系、180 证据，保持 partial。10 月 30 日 Flask 共享账本保守累计 9.465795 元（cap=19.84）。

公共接口见[流水线与CLI](docs/public_interfaces.md)、[图与查询](docs/graph_query.md)、[模型与证据](docs/p4/models.md)；[公开冻结重建包](repro/README.md)可无网络回放来源并重建图和索引，不需要本组密钥。原型入口为 `app/main.py`。10 月 30 日实验的[技术报告](reports/technical_report.md)、[PDF](output/pdf/historykg_technical_report.pdf)和[十页详细汇报](demo/final/期末汇报_20261030最终版.pptx)按原版本归档。逐项课程验收见[demo验收矩阵](evaluation/results/course_acceptance.json)。

**已完成的前期工作归属P4：** 项目起初调研、总体方案起草、多轮架构迭代、现有全部规划与规划协作框架、独立原型和期初小规模真实试跑，均由P4独立负责完成，计入其累计贡献。详见[P4前期工作与贡献记录](deliveries/P4/2026-10-27/handoff.md)，后续报告分工与展示引用该记录。

**2026-11-21 v1 期末基线说明（已由上文 v2/v7 增强并保留原汇总）**：此前第一版统一 `ItsDangerous` 冻结主线的实验汇总保留于 `evaluation/itsdangerous-final-20261121/`（[qa-summary.json](evaluation/itsdangerous-final-20261121/qa-summary.json)、[extraction-summary.json](evaluation/itsdangerous-final-20261121/extraction-summary.json)、[summarize.py](evaluation/itsdangerous-final-20261121/summarize.py)），仍可在解包目录下用 `tools.summarize` 复核。

## 完整系统：安装与运行

Windows PowerShell，在仓库根目录运行：

~~~powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force .local
Copy-Item config/project.example.json .local/project.json
~~~

在本机`.local/project.json`设置PostgreSQL地址及自己已批准的共享账本额度；通过环境变量配置GitHub只读访问、`DEEPSEEK_API_KEY`和`HISTORYKG_NEO4J_URI`。不复制本组密钥或账本路径。服务安装见[采集器说明](docs/collector.md)，原生Windows自动化步骤见`tools/ci/start_windows_services.ps1`。首次建图会访问GitHub和模型并产生相应账户费用。

~~~powershell
.venv\Scripts\python -m historykg.cli doctor
.venv\Scripts\python -m historykg.cli build https://github.com/pallets/flask
.venv\Scripts\python -m streamlit run app/main.py
~~~

页面可直接输入URL并观察同一持久作业，发布后输入自然语言问题。CLI的`build-status`只读状态，`resume`从未完成阶段继续；全部选项见`.venv\Scripts\python -m historykg.cli --help`。需要无新增模型费用地重建已交结果时，按[冻结重建说明](repro/README.md)操作，不重新build。

## 项目历史采集器

现行采集模块由 HistoryKG 直接访问 GitHub：自动选取讨论、读取分页、记录缺口和请求额度，并冻结原文及出处。中断后可沿用已存的响应继续采集。抽取、建图和问答共用同一批冻结来源。[安装与调用说明](docs/collector.md)覆盖 SQLite、PostgreSQL 及数据接口；早期原型与实验的来源见[第三方说明](THIRD_PARTY_NOTICES.md)。

macOS快速示例，在仓库根目录运行：

~~~sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m historykg.collector doctor
.venv/bin/python -m historykg.collector ingest https://github.com/pallets/flask
.venv/bin/python -m historykg.collector search 'Flask' --repo pallets/flask
~~~

默认开发小样最多一个PR和一个Issue，使用本地SQLite；PostgreSQL为正式主线。它不调用模型，不是完整系统的自动建图验收。源码、基础接口、验证及交接均计入P4的已完成贡献。

## 成员如何开工

首次把本人对应的一份完整工作单交给AI；AI已有仓库访问时，给该文件路径即可。**AI必须先只读理解，并在聊天中向成员讲清项目原理，再开始实施。** 讲解覆盖成品目标、自动获取新仓库资料、API与费用、数据三种用途、模型/图谱分工、开发测试隔离、六人协作与本人职责，结合具体例子和当前进度，不能只说“已理解”或发送文档链接。完整要求见[统一执行契约C0](01_统一执行契约.md#c0-开工前必须向成员讲清项目原理)。

本项目调用现成模型，不训练或微调基础模型。运行资料增加可查询范围，开发样本用于发现问题后修改程序，独立测试用于评价冻结后的效果。软件不依赖预装Flask数据；使用者配置自己的API Key及数据库后，为新仓库自动获取并保存资料，复用的是处理程序。课程另附冻结实验资料供复现。

讲解结束后，AI按已有授权检查环境、恢复/建立个人分支并开始首个可运行产物，不要求成员答题或回复“可以开始”；成员提问先解答。只收到通用规划且无法唯一确定角色时才询问分工。

后续恢复会话时，AI自行读取STATUS、最新交接、请求和现有成果，核对handoff中的讲解发送记录；无记录先补讲，有记录且目标/角色未变则简述现状继续。缺上游先登记请求并推进独立任务；常规提交、审核、技术确认、集成、报告和PPT都由角色AI完成。已有实现与正式质量验收分别依据实际运行记录。

| 角色 | 工作单 |
|---|---|
| P1 数据与集成 | [P1工作单](P1_数据与集成_给成员AI.md) |
| P2 图谱与查询 | [P2工作单](P2_图谱与查询_给成员AI.md) |
| P3 代码与演化 | [P3工作单](P3_代码与演化_给成员AI.md) |
| P4 项目历史采集、基础数据接口与模型抽取 | [P4工作单](P4_模型与知识抽取_给成员AI.md) |
| P5 原型与汇报 | [P5工作单](P5_原型与汇报_给成员AI.md) |
| P6 模型参考与实验 | [P6工作单](P6_模型参考与实验_给成员AI.md) |

P4使用macOS，其余Windows；P2使用现有DeepSeek可执行开发工具，其余五人Codex；全员已有DeepSeek API。除确需本人接管的环节外，全部项目工作交给AI。成员只处理本人登录/权限、缺少或超出已批预算的费用决定、必要设备动作、理解与现场表达和真实互评。代码、配置、数据核验、评分、交接、报告/PPT与打包均由AI执行；不安排逐条人工标注评分。

“自动开工”指AI在已经打开且具备相应工具权限的会话中，先完成上述讲解再执行；仓库文件不负责启动另一台电脑或唤醒已结束的会话。会话恢复后AI按记录自行续做，不要求成员重述方案。

成品的自动运行另由P1交付持久任务和单worker：P3自动补代码/提交/发布，P4自动抽取，P2自动建索引与图，P5显示任务并接通问答，P6检验全过程及质量。它不依赖六位成员的开发AI会话一直在线。

## 组长与维护入口

- [总规划与组长使用说明](00_总规划与组长使用说明.md)
- [统一执行契约](01_统一执行契约.md)
- [relore与Flask可行性记录](02_relore与Flask可行性记录.md)
- [范围与契约变更记录](03_范围与契约变更记录.md)
- [成员与仓库登记](coordination/成员与仓库登记.md)
- [当前修订与检查记录](deliveries/planning/2026-10-28-v1.4.1/README.md)
- [v1.4.0采集器与基础接口交付](deliveries/planning/2026-10-27-v1.4.0/README.md)
- [v1.3.2身份与样本单位修正](deliveries/planning/2026-10-27-v1.3.2/README.md)
- [v1.3.1执行要求精简](deliveries/planning/2026-10-27-v1.3.1/README.md)
- [v1.3.0试跑反馈修订](deliveries/planning/2026-10-27-v1.3.0/README.md)
- [v1.2.0自动建图目标修订](deliveries/planning/2026-10-26-v1.2.0/README.md)
- [v1.1.1降风险修订](deliveries/planning/2026-10-26-v1.1.1/README.md)
- [v1.1自动开工修订](deliveries/planning/2026-10-26-v1.1/README.md)
- [v1.0初始交付记录](deliveries/planning/2026-10-26/README.md)

期中：**2026年11月11日，每组5分钟**。内部完整候选：**12月20日**。实际期末提交日期以老师通知为准。

主要实验对象为[pallets/flask](https://github.com/pallets/flask)。代码、提交和发布由代码与版本模块从官方 Git/GitHub 来源补充。历史实验保留原采集与检索版本；当前版本可从公开冻结数据重建索引和图谱。

## 检查规划资料

PR和main提交自动运行Planning checks，成员无需手动触发、打卡或填表。检查只用公开文档和合成回归，不调用付费模型。对应角色AI查看结果并修复，真实系统由接收方AI另行复跑验收。

以下命令也可由AI本地运行，文档绿灯不代表系统运行通过：

~~~text
python tools/sync_workorders.py
python tools/check_planning.py
python -m unittest discover -s tools -p "test_*.py"
~~~

Windows可使用py -3运行，macOS可使用python3。工具仅用Python标准库。检查接受六种合法进度状态，日期使用实际执行时的北京时间；--initial-snapshot仅用于额外核验初始全todo快照。六份工作单的公共段必须与统一契约一致，状态文件中的后续实现不得提前标完成。
