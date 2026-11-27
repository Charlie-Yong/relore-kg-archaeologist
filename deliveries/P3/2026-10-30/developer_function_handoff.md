# P3 Developer / Function 增量交接

日期：2026-10-30；角色：P3；分支：`feat/p3`；实现提交：`7031c0c`。

## 范围与原理说明

本轮已在聊天中向成员发送 C0 八项项目原理与 P3 职责说明，随后实施；不冒称成员确认。
修改只位于 `historykg/code/`、`tests/test_code.py`、`docs/code.md`、本交接与同目录验证 JSON。
未修改 `contracts.py`、主目录、其他 worktree、生产数据、模型或私有测试。

新增事实只来自冻结来源：Developer 读取 P1 已保存的 PR API JSON 顶层 `user` 和
`merged_by`，不读取 commit author，也不生成 Developer→Commit；Function 只读取已采
24 个文件×SHA 状态内的源码 AST，不增加文件预算。旧 1.4.1 记录保持只读；新 Developer、
Function、Authored、Merged、Defines 使用 P2 的增量契约 1.4.2。

## 实际输出

- Developer：优先以 GitHub 数字用户 ID 构造 `identity_key=github:<id>`；无 ID 时使用
  `login:<casefold(login)>`。`display_name` 与 `login` 均为原文 login，不猜真实姓名。
- `Authored`：Developer→PullRequest，证据为 PR JSON 顶层 `user` 的完整原文对象。
- `Merged`：Developer→PullRequest，仅对已合并且含 `merged_by` 的 PR 生成，
  证据为顶层 `merged_by` 原文对象，`occurred_at` 使用 `merged_at`。
- Function：仅顶层 `FunctionDef`/`AsyncFunctionDef`，不收 ClassDef 或方法。属性含
  `qualified_name`、`kind`（`function`/`async_function`）、`start_line`、`end_line`、
  完整 SHA、路径、源码 URL 与签名。稳定键保留
  `sha/path/qualified_name/start_line`，以区分同文件重复定义。
- `Defines`：同 SHA 的 File→Function，证据逐字引用函数签名，使用 Unicode 码点偏移。

实现版本为 `code_v2` / `python_ast_v2`。实现版本已纳入冻结输入哈希，因此旧数据目录不会
被新代码静默覆盖；端到端必须创建新数据版本。

## 真实冻结只读重放

使用原 Flask job `b61942bf06b742e48860d064dffe6df2` 的冻结 snapshot 和 P1 本地裸 git 缓存，
在临时目录重放。最终记录运行的网络请求、git 网络操作和模型请求均为 0，生产 P3 四分片哈希
未变。完整数据见 [developer_function_validation.json](developer_function_validation.json)。

实际可生成：

| 项目 | 数量 |
|---|---:|
| Developer | 18 |
| Function | 384 |
| Authored | 20 |
| Merged | 4 |
| Defines | 384 |
| 文件×SHA | 24 |
| 总证据 | 508 |

固定目标链已核对：

```text
PR #6096 (author lkk7, merged_by davidism)
→ commit 05e9c6bd630ecf4ec0ec884b1fc7901663737bc7
→ src/flask/testing.py
→ flask.testing._get_werkzeug_version
```

该函数 `start_line=100`、`end_line=106`；`FlaskClient` 是 ClassDef，未生成 Function。
全部 508 条证据均通过原文 Unicode 区间复核；Authored/Merged 端点均为 PullRequest，
Defines 端点为同 SHA 的 File/Function。两次全新重放的 Developer、Function 和三类新关系
ID 完全一致。新增记录已用 P2 工作区草案契约 1.4.2 做只读模型校验：96 来源、508 证据、
430 实体、449 关系全部通过，其中新实体 402、新关系 408。

探索性重放时，空的 Release/tags 曾触发 1 次只读 tags GET；该临时输出已丢弃。正式记录运行
显式使用冻结空集合，网络为 0。没有把任何临时输出写入生产数据集。

## 检查结果

```text
PYTHONPATH=.:vendor/relore python -m pytest tests/test_code.py -q
9 passed

PYTHONPATH=.:vendor/relore python -m pytest tests -q
127 passed, 28 skipped

python -m ruff check historykg tests
All checks passed!

git diff --check
exit 0
```

28 个 skip 是未配置的 PostgreSQL/Neo4j 等可选环境检查；不是本轮新增跳过。定向测试覆盖
多作者、无作者、login-only 回退、async、Unicode、同名跨文件、同文件重复定义、ClassDef
排除、证据定位、稳定 ID、共享预算、缓存重放和旧数据消费兼容。

## P2 集成事项

1. P2 合并 1.4.2 后按真实字段接收 `Developer.key=identity_key` 与含 `start_line` 的
   Function 键；不要压缩为仅 qualified_name。
2. 新关系端点为 `Authored/Merged: Developer→PullRequest`、`Defines: File→Function`。
3. 完整目标链中的 PullRequest 实体与 PR→Commit 的 `MergedAs` 由 P1 提供；P3 不重复生成。
4. P1 在新 job/dataset 上跑端到端；旧 1.4.1 冻结数据继续只读，不在原目录补写 1.4.2。
5. P2 的图加载与主体/查询规则需接受 Developer/Function；P3 不修改 `graph/query`。

恢复动作：从 `7031c0c` 后接 P2/P1 集成；如下游失败，回传最小失败记录和实际 JSONL 行，
由 P3 在本人分支修复，不重采或手改生产数据。
