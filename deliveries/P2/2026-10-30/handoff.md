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
