# P3 代码与演化交接

日期：2026-10-30；角色：P3；契约 1.4.1；分支 feat/p3。
当前为 `ready_for_integration`，角色整体尚未完成。

## 原理说明与边界

本轮根协调会话已向用户发送完整 C0 八项原理讲解。P3 只读完整 AGENTS、本人工作单、
STATUS、10月27日试跑与 P4 交接后，通过 agent message 向根协调会话发送了 P3 的输入、
处理、输出和具体 git 改名/删除/Imports 例子，随后才开始修改。实际发送方式是根会话聊天
加 P3→根 agent message；本记录表示已发送，不冒称成员已确认理解。

任务是从 P1 固定快照自动补代码事实，不新增公共格式，不调用付费模型，不读取 P6 私有测试。
保留 P4 前期设计、试跑与基础接口贡献。当前实际使用 macOS，未标 Windows 通过。

## 版本、输入与产物

- 公共接口首批 e0f4ab2 已普通 merge（fast-forward）到本人分支。
- 本人代码提交：`41d6020`，提供 `historykg/code/` 和 `tests/test_code.py`。
- 文档/能力/状态提交：`20f2e1a`。已成功推送 `origin/feat/p3` 并创建
  [PR #3](https://github.com/Charlie-Yong/relore-kg-archaeologist/pull/3)。
- 输入是 P1 `snapshot_dir/snapshot.json`，包括规范 repo、dataset_id、完整 selected_prs，
  可带 default_branch_sha、已有 SourceDocument 及 Release/tag 官方对象。
- 生产入口：`historykg.code.run_code_stage(snapshot_dir, *, dataset_dir, profile, budget)`。
  返回 `status/artifacts/counts/gaps/usage`，仅写 p3 四分片及 plan/gaps/manifest/state/api_cache。
- 独立入口：`collect_code(snapshot, *, dataset_dir, profile=None, budget=None, client=None,
  git_repo=None)`，后两项用于冻结响应和本地 git 测试。
- [调用与规则说明](../../../docs/code.md)；[方法章节素材](method_notes.md)。

实体为 Commit/File/Release；关系为 Touches/ChangesTo/Imports/HasRelease/MentionsPR/ReachableIn。
所有 ID、来源、证据和 JSONL 直接调用 P1 公共函数。PullRequest 与 Project 端点由 P1 提供，
P3 不重复生成 MergedAs。File aliases 包含路径与顶层类/函数名，P1 build_subjects 已可消费。

## 范围与证据口径

最多 40 commit、24 个文件×SHA、3 Release/tag。生产文件优先、提交轮转采样；总文件配额中
预留最多 8 个给默认快照包入口及一层内部 import 目标。没有按测试问题或 Flask 固定编号补采。
官方 git 只读裸对象缓存，每次 fetch 最深 64。正可达由真实 merge-base 退出 0 支持，浅历史
否定保留 unknown。notes 提及只表示提及，不宣称首次引入或首次修复。

删除指向父版本；ChangesTo 只用显式同路径/rename；AST 仅连接已采同 SHA 目标。
来源哈希、Unicode 偏移、真实命令与 stdout/returncode 可复算。完整 API 响应使用 P1 冻结 JSON，
同一完整响应在多个发布实体间复用；已有同 ID 上游来源复用原记录，避免采集时间冲突。

budget 使用共享可变 dict 的 max_requests/github_requests。API 每次尝试与 git fetch/ls-remote
网络操作都先计入总额，P3 返回本次增量和累计 total；P1 已确认持久化 total，不重复相加。
相同输入和校验输出重放不增请求。失败保留前缀和 gaps，输入变化拒绝覆盖旧数据版本。

## 实际检查

真实环境：macOS 27.0.1 arm64、Python 3.11.15、git 2.54.0。使用主副本已有 Python 环境，
显式设置 `PYTHONPATH=<P3根>:<P3根>/vendor/relore`，核验 import 路径确在 P3 副本。
公开 GitHub 仓库元数据 GET 返回 200；此 shell 无 GITHUB_TOKEN/GH_TOKEN，未泄露凭据。

在本人副本根运行：

```text
python -m ruff check historykg/code tests/test_code.py
python -m pytest tests/test_code.py -q
python -m pytest tests -q
python tools/check_planning.py
git diff --check
```

ruff 全通过；P3 七项通过。完整 tests 为 **22 passed、11 skipped**，未配置的 PostgreSQL
检查明确跳过；Planning checks 通过，163 个本地链接有效；git diff --check 通过，全部退出码 0。
P3 测试用本地真实 git commit/tag/diff 对象，未运行 toy 或目标项目代码；包含修改、删除、
显式 rename、语法失败、普通/相对 import、缺失/读取失败、Unicode、不同 tag、可达、
共享预算、缓存和输入冻结；同时实际执行 P1 merge_sources/build_subjects/validate_dataset，
跨分片端点、来源哈希、证据区间和自动 aliases 检查通过。

本轮付费模型请求 0，费用 0。没有真实 Flask URL 验收数据，不把 fixture 冒充真实采集。

## 已发送交接与下一恢复点

P3 与 P1 已通过 agent message 直接约定并确认入口、snapshot.json、字段、公共函数、
预算计数及 source/aliases 消费。P3 已向 P1/根发送 `41d6020` 和七项通过记录，
请求 P1 普通 merge 后接入真实 URL 流程。当前没有接收方真实运行结果，未写 verified_real。

下一步由 P1 用 Flask URL 自动产生固定快照并调用本模块；P3 在同一上下文接收最小失败记录
继续修复和补实际代码链/架构题素材。P2 验收 graph import、P4 回答依赖/职责题、P5 展示，
均待真实联调。公开 GitHub 账户/网络限流如出现将按真实状态保存，不要求成员手填 SHA。
Windows 实机、正式来源冻结、独立工程复核、课程实验与最终章节仍待后续阶段。

根协调会话提醒并已发 P1：snapshot.paths.sources 必须指向不可变 code 阶段来源快照，
不能指向随后会扩充的全局 sources.jsonl。读取的实际来源属于 input_hash，resume 沿用相同阶段输入。

本批按 C3.3 已运行受影响检查，待接收方的阶段集成及独立工程复核；没有新建付费审核。

## 真实 Flask URL 闭环核验（2026-10-30）

P1 原job `b61942bf06b742e48860d064dffe6df2` 已用同一 URL 自动作业完成 `code` 阶段，
dataset 为 `dataset:810db3718867788c5acb0fa437cdbf62bc0f99cd8e7435e9261471225f5cd00c`。
这不是 fixture 回放：job 的 `stage_statuses.code` 为 `ok`，P3 分片包含 94 个来源，
其中 24 个为 `code` 原文来源；共有 4 个 Commit、24 个 File 快照、3 个 Release、
25 条 Imports、8 条 Touches、8 条 ChangesTo、3 条 HasRelease 和 104 条证据。
24 个 Python 文件全部解析成功，模型请求为 0。

复核使用主仓库公共 CLI 校验整个 dataset，结果为 `status=ok`、零错误；随后逐项检查：

- 94/94 来源文本的 UTF-8 SHA-256 与 `text_sha256` 一致；
- 104/104 证据的 Unicode 区间与原文 quote 一致；
- 24/24 File 均可定位到同 repo、同 SHA、同 path 的 `code` 来源，且 `plan.file_selections`
  与实体集合完全一致；
- 44/44 关系的端点存在；25 条 Imports 均连接同 SHA File，证据来自源文件原文；
- entities/evidence/gaps/plan/relations/sources 六个分片哈希全部与 manifest 一致。

真实架构题“提交 `514fc6b3…` 的 `src/flask/testing.py` 中
`FlaskClient.session_transaction` 承担什么职责”返回 6 条 claims，全部证据均可定位到该
冻结路径与 SHA，Unicode 区间和来源哈希均通过。该结果验证源码证据链和职责回答素材，
不冒充独立语义准确率实验。冻结重放中的旧 `trace` 题仍保留原 `empty`，不把 P2 后来的
v2 排序修复回写成原响应。

机器记录见 [platform_validation.json](platform_validation.json)。P3 分片的明确限制为：
12 个 PR/tag 因深度 64 浅历史而可达性 unknown；181 个内部 import 目标不在 24 文件预算；
5,309,480 码点全池中其余外部/未解析 import 也保留在 gaps。静态 AST 和 git diff 不代表
运行目标代码、完整调用图或未采依赖完整性。

本轮恢复检查实际为 `tests/test_code.py` 7 passed；P3 页面汇报接续前的当前主线全量测试为
**125 passed、28 skipped**，P3模块Ruff、规划检查（225个本地链接）和`git diff --check`
全部通过。没有新增 DeepSeek 或GitHub网络请求。
