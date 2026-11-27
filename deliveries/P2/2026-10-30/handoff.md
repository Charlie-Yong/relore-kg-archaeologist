# P2 图谱与查询交接

角色P2；2026-10-30；规划/公共契约1.4.1。阶段：ready_for_integration。

## 输入与新增产物

已向主代理发送P2输入/处理/输出与Decision→PR→Commit→File的trace原理说明，
由主代理已发送的C0完整讲解衔接本角色；未冒称成员确认理解。
完整读取P2工作单、AGENTS、公共契约、STATUS、P4交接与历史试跑缺陷后实施。
保留P4前期独立设计、原型、试跑和relore基础接口贡献。

本轮基于主仓库本地main `f3e2a71`（含P1 `e0f4ab2/83aba79`和P3 `2fb6d55`），
本人分支feat/p2，唯一副本relore-agents/p2。保护原有文件，无其他角色目录修改。

- `historykg.graph.load_dataset(dataset_dir,config=...)`：统一验证、dataset隔离、
  Neo4j约束/事务/幂等冻结与读回校验，真实图/检索就绪和拒收报告。
- `historykg.query.query(request,config=...) -> QueryResult_v1`及无模型`prepare_query`：
  同源relore+固定适配、共同种子、图路径、证据映射、P4回答器接入与运行留档。
- [接口与方法](../../../docs/graph_query.md)、`tests/test_graph_query.py`。

## 实际验证与证据

实际平台macOS，Python3.11.15；主仓库.venv/bin/python配本人`PYTHONPATH=vendor/relore:.`，
historykg和relore导入路径均已确认指向本人副本；neo4j5.26.0由P1统一安装并锁定依赖。
课程Neo4j `bolt://127.0.0.1:17687`，PostgreSQL16.4课程库及专用_test库可用。

真实toy_v1首次载入：12sources、11entities、14relations、12evidence、5subjects；
graph_ready/retrieval_ready均true，指纹`196064d309676a117d901ed794c1efea4ee499d54290fca1df647eabebf82ac2`。
自然语言“Why keep the cache API?”真实trace返回35路径/10候选；纯合成材料不当真实Flask答案。

命令（均本人副本，主venv python）：

```text
P2_TEST_NEO4J_URI=bolt://127.0.0.1:17687 P2_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:16432/historykg_course_test PYTHONPATH=vendor/relore:. python -m pytest tests/test_graph_query.py -q
# 14 passed in 1.12s；exit 0
python -m ruff check historykg/graph historykg/query tests/test_graph_query.py
# All checks passed
git diff --check
# exit 0
```

覆盖真实重复导入不增长/隔离、错误偏移/缺端点/跨dataset/来源缺失整批拒收、
同dataset冻结变更拒收、去Decision仍有Issue/PR/Commit/File链、声明不升级关闭、
相同SHA下v1.0/V1.0身份不合并、A/B相同种子来源且A可见代码、四种返回状态、
五kind合法响应、断图/断检索为error、回答不得引用最终不可见片段、外库同号不串主体。
测试只清理随机p2_test数据集，无全库删除；测试回答器明确标记synthetic_test_only。
没有新增付费模型调用，没有独立ledger，没有访问P6私有资料。

## 接收方与恢复

P1已确认pipeline/CLI按本接口传入graph配置、根database_url及P4 answer/budget；
load返回dict，query返回公共Pydantic，CLI统一model_dump。P4回答器即将提交，
复用其render_context与唯一共享账本；真实模型联调待该提交后继续。
P1/主代理需按C3.3实际复跑本模块并做独立工程复核，当前不标verified_real/done。
尚待：真实Flask数据load/query、架构职责实答、
11月11日展示真实缓存、Windows实机、P6正式实验与课程章节后续材料。

## 接收复核后的实际接缝修复（同日）

主代理已独立复跑首批14项真实namespace测试全部通过，并检查代码；反馈正常
query配置缺P4回答输出目录、同repo刷新会污染旧dataset的relore排名，另需路径实体可读。
同步主仓库main0855735（含P4 776e556、P1 7dba6c5）后，本批修复：

- answer_output_root默认本数据集llm，显式配置仍优先；不再要求普通用户填内部目录。
- 每dataset在同一Postgres实例独立schema回放实际P4 ThreadPayload，逐条验证原对象与
  C5讨论正文；命中仍调用真实search_history，索引描述符不保存凭据。
  exports/relore_input.json保存可搬迁的原始输入，随冻结包交付；SQLite开发使用单独文件。
- path.entities返回当前数据集已存Entity及Source轻量标题，P5可读展示，不新增业务实体。
- 真实relore datetime命中转换为ISO字符串再写审计；QueryResult透出usage/model_run_id。

新增针对性验证（实际PostgreSQL16.4/Neo4j5.26.0）：同repo原对象old→全局index_payload
upsert new→第二dataset回放，旧dataset的raw命中/排名/候选完全不变，新dataset命中新文本。
真实P4 answer_question链使用无付费run_request替身验证默认目录和真实renderer，
最终JSON<=12000码点、长来源在完整句/行边界裁剪且end/quote一致。真实模型不调用，
不把该替身结果当成Flask质量证据。原测试受影响部分与新增测试共同检查：
`tests/test_graph_query.py`最终16 passed in 2.57s（exit0），ruff/规划检查/diff检查均通过。

P6已接收最终context字段位置；P5已确认path.entities接口。未提前发布P1待extract的
Flask同ID数据集，待独立参考先行完成、主代理唯一恢复生产流水线后再实问。

已push feat/p2并创建[PR #5](https://github.com/Charlie-Yong/relore-kg-archaeologist/pull/5)，
修复提交0209e47。主代理按依赖顺序合并其他角色后，PR祖先差异自然收窄；不重写长期分支。
新增[报告方法草稿与核验引用](method_notes.md)、[期中片段口径](midterm_notes.md)，
均只使用已有实际实现/工程结果，不填写待运行Flask实答或正式实验数字。

## 公开dev-01空回答定位（同日）

P5真实冻结回放的dev-01返回empty，模型gap说明最终上下文只含issue正文，未含维护者评论。
只读复跑候选池确认issue正文与三条关键维护者评论都已被检索，但图扩展和通用API/代码
候选把正文与评论挤出12000码点。这是候选排序缺陷，不是主体未解析或来源缺失。

`relore_common_rrf_graph_v2`对A/B使用同一直接范围排序：问题明确指向Issue/PR且没有
代码路径/SHA时优先issue_body、comment、review、pr_body，降低通用API元数据；问题明确
给出路径或提交SHA时优先origin_key匹配的code快照。图扩展只作为同一直接相关层的次级
排序。修订后对原Flask冻结数据集无付费复跑`prepare_query`与共享`render_context`：
候选状态ok，最终5个片段均为issue正文/评论，包含“They should be calling `close` on
the iterator”及“server's control at that point”；未调用回答模型，不据此声称新回答正确。
机器可读记录见[dev01_context_fix.json](dev01_context_fix.json)。

P6若已在旧`relore_common_rrf_graph_v1`协议下开始正式答题，应保留原冻结结果并披露本次
修复为后置；后续正式运行须重新冻结v2方法哈希，不能把两版上下文混在同一实验。

实际回归：`tests/test_graph_query.py`在真实PostgreSQL/Neo4j上18 passed；ruff通过。
新增用例覆盖“Issue讨论优先于高分通用API/代码”和“显式路径/SHA的代码快照优先”。

## 1.4.2 图谱实体覆盖与 P3 形状修复（同日）

为课程选题补齐公共实体`Developer`、`Function`，保留原实体/关系不变，并新增
`Authored(Developer→PullRequest)`、`Merged(Developer→PullRequest)`、
`Defines(File→Function)`；没有Feature，也没有无证据的Developer→Commit。
Neo4j为`HGDeveloper/HGFunction`增加dataset内`(dataset_id,id)`约束和类型标签，
加载、读回、端点校验与查询路径均覆盖新实体；旧1.4.1 fixture仍可加载。

Developer以P3当前重放分片的标量`key=identity_key`为准，校验器同时兼容早期交接的
单元素`key=[identity_key]`；identity_key为`github:<id>`或
`login:<casefold(login)>`，稳定ID为`entity_id("Developer",repo,identity_key)`。
Function按`key=[sha,path,qualified_name,start_line]`并以相同四项生成稳定ID，
同名不同行不会合并。查询主体回退只使用标量属性形成Developer/Function别名，不把
列表key字符串化。已发布`relore_common_rrf_graph_v2`的正式A/B默认仍为3跳；展示
Developer→PR→Commit→File→Function必须显式传`graph_depth=4`，必要时再显式提高
`graph_path_limit`（默认50、上限100）并关闭验收查询的来源种子追加
（`graph_expand_seeds=false`），不改变正式A/B默认行为。

真实Flask冻结数据跨源验收和机器可读证据见
[`evaluation/results/cross_source_chain.json`](../../../evaluation/results/cross_source_chain.json)。
P3实际重放分片有18 Developer、384 Function、20 Authored、4 Merged、384 Defines，
manifest的代码阶段本地model_requests=0（非整个历史生产抽取计数）；Developer key为
标量`github:<id>`/`login:<casefold(login)>`，
Function key为四元`[sha,path,qualified_name,start_line]`。与P1冻结包合并后的数据集
`p2_p3_real_014e28d89e1f`为sources 370、source_units 40、evidence 741、entities 535、
relations 591、subjects 65，真实`validate_extended_dataset` status ok且
`historykg.graph.load_dataset` graph_ready/retrieval_ready均为true，fingerprint
`d0c1be456f70acdf354776e2fbee24ee5d6614e94437add2a3e90239a48539dd`。

使用随机测试namespace和PostgreSQL schema，显式
`graph_depth=4, graph_path_limit=100, graph_expand_seeds=false`运行PR #6096链：
run_id `query-0746f75077e84b6f8759782dd7a76d80`，status ok，99路径、53 evidence、
0请求/0模型；两条匹配路径分别为
`lkk7→PR→Commit→File→Function`（Authored→MergedAs→Touches→Defines）及
`Function→File→Commit→PR→davidism`（Defines→Touches→MergedAs→Merged）。
测试结束后两个临时namespace均已清理。正式A/B默认仍为3跳/50路径/启用来源种子扩展。

可直接展示的问题：

```text
Issue #6093 报告 IPv6 地址解析问题。请沿 PR #6096（作者 lkk7、合并者 davidism）
追到 merge commit 05e9c6bd630ecf4ec0ec884b1fc7901663737bc7、src/flask/testing.py
以及顶层函数 flask.testing._get_werkzeug_version。
```

真实`tests/test_graph_query.py`（Neo4j 17687 + PostgreSQL 16432/test库）为26 passed，
全套pytest为149 passed / 13 skipped，Ruff与`git diff --check`通过。生产只读查询
status ok且不调用模型，但当前生产图无Developer/Function，只能覆盖PR→Commit→File。
该缺口已写入机器可读证据，不将测试namespace的4跳结果冒充生产节点。
本轮新增/修订回归位于`tests/test_graph_query.py`和`tests/test_contracts.py`，
覆盖P3实际Flask身份ID、同文件同名不同`start_line`、错误key/ID、缺行号拒收、
默认3跳与显式4跳差异。测试服务由主代理唯一管理，P2未启动、停止、重启Neo4j或PostgreSQL。
