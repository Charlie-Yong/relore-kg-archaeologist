# P3 代码与版本采集

本模块接收 P1 的固定发现快照，自动补充官方 git、Python 原文和有限发布资料。
它只静态读取目标仓库，不安装、导入或执行目标代码，不调用付费模型。
公共来源、ID、证据和校验直接使用 `historykg.ids`、`historykg.io`，契约为 1.4.1。

## 调用与输入

流水线入口由 P1 调用：

```python
from pathlib import Path
from historykg.code import run_code_stage

result = run_code_stage(
    Path(".local/jobs/<job_id>/code-input"),
    dataset_dir=Path("data/<dataset_id>"),
    profile={"max_commits": 40, "max_file_snapshots": 24, "max_releases": 3},
    budget={"max_requests": 300, "github_requests": 120},
)
```

`snapshot_dir/snapshot.json` 至少包含 `repo`、`dataset_id`、`selected_prs`。
`selected_prs` 是已经冻结的官方 PR 对象，保留 `number`、`merged` 或 `merged_at`、
`merge_commit_sha`。没有合并依据的条目排除并记录原因，不用标题推测提交。
可提供 `default_branch_sha`、`releases`、`tags` 和已有 `sources`；
`paths.sources` 可指向已有 C5 来源 JSONL。未给默认分支 SHA 时从官方 git HEAD 自动固定；
未给发布资料时读取官方 Releases API，按发布时间取最多三个，空时按 tags 接口顺序回退。
源码目录、PR、版本和路径均不需要终端用户手填。

独立开发入口为 `collect_code(snapshot, *, dataset_dir, profile=None, budget=None,
client=None, git_repo=None)`。`client` 和 `git_repo` 用于冻结响应与本地真实 git 对象测试；
合成 `example/toy` 数据不能作为 Flask URL 验收材料。

## 范围与恢复

- 最多 40 个选中合并提交、24 个 Python 文件×SHA 状态、3 个 Release/tag。
  同一 SHA/path 去重；同路径不同 SHA 保持不同 File ID。
- 变更候选按生产代码优先、每提交轮转选择。24 状态中预留最多 8 状态，
  自动读取默认快照中最浅包入口及其一层内部静态 import 目标，供有限架构问答。
  入口优先 `src/`，没有包入口时用生产 Python 文件。此规则不依赖未来测试题。
- 所有 API 尝试以及 git fetch/ls-remote 网络操作，都在请求前递增共享
  `budget.github_requests`，总计不超过 `max_requests`（最高 300）。
  `usage.github_requests` 是本次增量，`github_requests_total` 是当前累计，不能再次重复相加。
- git 使用裸对象缓存，不 checkout。默认缓存 `.local/code-git/`，可用
  `HISTORYKG_CODE_CLONE_ROOT` 配置；每次 fetch 深度最多 64。
  正可达必须由实际 `git merge-base --is-ancestor` 退出 0 支持；浅历史否定结果记 unknown。
- P3 只写 `dataset_dir/p3/` 的 sources/entities/relations/evidence 四分片，以及
  plan/gaps/manifest/state/api_cache。P1 合并来源、生成 subjects 并最终校验冻结。
- 同输入已有完整可校验输出时按哈希重放，不新增请求。中途预算/外部失败保存已有前缀；
  恢复沿用同一快照及 API 缓存。输入变化会拒绝覆盖，要求新的数据版本。

## 关系与证据

`Touches` 指提交后文件；删除时指真实父 SHA 中的旧文件，并注明 deleted 和 parent_sha。
`ChangesTo` 只连接显式同路径或 git rename 的前后状态；copy 不视为同一历史。
`Imports` 只连接已经读取的同 SHA File，保留实际 import 原文、Unicode 码点区间和行号。
相对 import 超出包、目标未采、外部模块、语法错误与读文件失败分别进入 gaps。
AST 的 UTF-8 列号会转换为公共证据要求的 Unicode 码点偏移。

Release ID 使用规范 repo 与原样 tag，同提交的 `1` 和 `v1` 不合并。
Release notes 的 PR 引用只产生 MentionsPR；ReachableIn 只来自 git 可达，均不宣称首次发布。
API 证据保存完整响应的 P1 规范 JSON，一份响应供多个实体共享，不生成裁剪对象冒充原响应。
git_output 保存真实命令、输入和 stdout/returncode，可复算 diff、父链和可达事实。
File 属性附顶层符号名、docstring、aliases，供 P1 自动主体目录与回答时定位原文。

## 本阶段验证

在仓库根目录、Python 3.11 环境执行：

```text
python -m pytest tests/test_code.py -q
python -m ruff check historykg/code tests/test_code.py
```

本地 git fixture 覆盖修改、删除、改名、语法失败、普通与相对 import、缺失与读取失败、
Unicode 偏移、同提交不同 tag、可达、共享预算、缓存重放与冻结输入拒改。
测试还实际调用 P1 的 merge_sources、build_subjects、validate_dataset 验证下游消费。
默认真实 Flask URL job已完成本阶段的平台联调：4 个提交、24 个文件×SHA、3 个 Release、
25 条 Imports、8 条 Touches、8 条 ChangesTo、3 条 HasRelease 和 104 条证据。
全数据集 CLI 校验、94 个来源哈希、104 条证据区间、24 个文件和 44 条关系均通过复核。
深度 64 浅历史造成的 12 个可达性 unknown 与未采 import 目标继续保留为 gaps。
P3 的 Windows 兼容由 P1 跨平台 CI 单独记录；本模块仍不执行目标仓库代码。

方法依据：[Git diff-tree](https://git-scm.com/docs/git-diff-tree)、
[Python 3.11 AST](https://docs.python.org/3.11/library/ast.html)、
[GitHub Releases API](https://docs.github.com/en/rest/releases/releases)。
