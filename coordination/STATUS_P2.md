# P2 实施状态

角色：P2｜更新：2026-10-30｜规划v1.4.1 / 契约1.4.2（兼容1.4.1）。

状态：ready_for_integration（实现、真实服务回归、PR #6096四跳验收均完成）。

实际进度：公共契约新增Developer、Function及Authored/Merged/Defines；Neo4j
`HGDeveloper/HGFunction`约束、幂等导入、dataset隔离、端点校验和查询路径已接图。
Developer按P3当前的标量`identity_key`并兼容单元素`[identity_key]`、Function按含
`start_line`的四元key校验，旧1.4.1保持兼容。
已发布`relore_common_rrf_graph_v2`默认仍为3跳；4跳只由显式`graph_depth=4`启用，
必要时可另显式提高`graph_path_limit`（上限100）并关闭来源种子追加
（`graph_expand_seeds=false`），默认路径上限仍为50且正式A/B仍启用来源种子扩展。

真实P1冻结包与P3重放分片合并数据已通过`validate_extended_dataset`并载入随机测试
namespace：sources 370、source_units 40、evidence 741、entities 535、relations 591、
subjects 65，fingerprint
`d0c1be456f70acdf354776e2fbee24ee5d6614e94437add2a3e90239a48539dd`。
PR #6096派生4跳`QueryResult`为status ok、99路径、53 evidence、0模型调用，找到
lkk7→PR→Commit→File→Function及反向Function→File→Commit→PR→davidism两条路径。
真实`tests/test_graph_query.py`为26 passed，全套pytest为149 passed / 13 skipped；
测试namespace和Postgres schema均已清理。Ruff与`git diff --check`通过。

最新记录：[P2交接](../deliveries/P2/2026-10-30/handoff.md)。
机器可读链证据：[cross_source_chain.json](../evaluation/results/cross_source_chain.json)。

残余缺口：生产dataset
`dataset:810db3718867788c5acb0fa437cdbf62bc0f99cd8e7435e9261471225f5cd00c`
当前仍只有PR→Commit→File，没有Developer/Function；四跳只在真实P1+P3合并shard的
测试namespace验收，未冒充生产节点。Windows实机和正式A/B实验仍待主代理后续运行。
P2未启动、停止、重启Neo4j/PostgreSQL或杀Java进程。
