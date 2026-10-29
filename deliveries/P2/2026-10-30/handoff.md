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
尚待：P4最终renderer联调与截断检查、真实Flask数据load/query、架构职责实答、
11月11日展示真实缓存、Windows实机、P6正式实验与课程章节后续材料。
