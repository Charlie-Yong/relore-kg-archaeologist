# 图谱导入与公共查询（P2）

接口契约1.4.1；本实现基于P4移植的relore和P1/P3/P4统一冻结记录。
Neo4j存储实体/关系与冻结来源、证据；本模块不采集、不推断新事实。

```python
from historykg.graph import load_dataset
from historykg.query import query, prepare_query

config = {
    "neo4j_uri": "bolt://127.0.0.1:17687",
    "database_url": "postgresql://postgres@127.0.0.1:16432/historykg_course",
    "answer": {"provider": "deepseek", "model_id": "deepseek-flash"},
    "budget": {"ledger_path": "<本机共享账本路径>", "approved_cny": 10, "max_cost_cny": 10},
}
loaded = load_dataset("data/<dataset_id>", config=config)
assert loaded["graph_ready"] and loaded["retrieval_ready"]
result = query({"dataset_id": loaded["dataset_id"], "question": "这个改动为什么做？"},
               config=config)
print(result.model_dump(mode="json"))
```

实际使用由P1的build/CLI和P5页面传入配置，用户只填仓库URL和自然语言问题。
上述数据库地址是本机课程服务示例；其他电脑使用自己的配置。
认证可配置`neo4j_user/neo4j_password/neo4j_database`，或本机环境变量
`HISTORYKG_NEO4J_URI/USER/PASSWORD`；不在仓库保存真实凭据。

## 导入

`load_dataset(dataset_dir, *, config=None)`返回字典，包含`dataset_id/status`、
`graph_ready/retrieval_ready`、`counts/rejected/error`、冻结指纹和可见来源清单。
先调用P1的`validate_dataset`核验偏移/哈希/身份/端点/关系类型/跨库记录和API事实，
再核对manifest完整来源表。校验失败时整批拒收，不悄悄丢弃坏记录。
实际relore数据库必须可读且schema就绪；Neo4j写完后读回所有记录并复算指纹。

Neo4j约束为`HGDataset(dataset_id)`及`HGRecord/HGEvidence(dataset_id,id)`唯一。
实体、来源分别标记`HGEntity/HGSource`，共同继承`HGRecord`以支持EVIDENCED_BY端点；
关系使用契约中真实方向与类型，全部绑定dataset_id。完整公共JSON保存在record属性，
不因Neo4j属性类型限制改变原始字段。整批在一笔事务中写入，最后发布ready标记。
同数据集、同冻结输入幂等；同dataset_id内容改变拒收，刷新须另开数据版本。
`GraphStore.delete_dataset(dataset_id)`仅清理明确命名空间，用于专用测试/明确重建。

## 查询与可见证据

`query(request, *, config=None)`返回公共Pydantic `QueryResult_v1`。
支持search/trace；timeline列已有时间关系；dependencies仅支持已有同SHA Imports；
compare要求确定的两侧File与ChangesTo。缺所需记录返回unsupported，查询不触发补采。
服务或输入数据损坏返回error；无匹配返回empty；claims始终由P4统一回答器生成。
无Decision时，Issue/PR/Commit/File链仍可返回。路径附每条实际关系和独立evidence_ids，
ClaimsToClose、Closes、MergedAs、MentionsPR与ReachableIn保留各自语义，不升级结论。

`prepare_query`运行真实检索/图查询但不调用模型，供检查候选、来源池和路径；
它不是模拟答案。问题从subjects名称/别名、当前库的#编号和URL解析种子，
也从共同检索命中的实体证据取得种子。并列主体返回候选缺口，不声称查全。
外库URL编号不映射成本地同号主体。

固定方法版本`relore_common_rrf_graph_v1`：先真实调用P4 `search_history`（10命中），
按P1 `relore_mapping`映射到本数据集来源；再对完整共同来源池使用固定词法适配，
包括讨论、code、release_note、commit_message、git_output、api_response。
词法为英语/标识符与中文二元词，标题加权，按得分降序、source_id升序；
两种排名通过`1/(60+rank)`合并。来源原文始终取当前冻结包，不取其他数据集文本。
底座命中、映射及可见来源清单保留在查询日志，不能把适配检索称为纯relore原生排序。

`config['system']='A'`关闭图扩展，`B`为默认；两组共用问题解析、初始种子、
来源池和词法/relore排名。B仅沿当前数据集的真实关系扩展，不从图引入新原文。
当前界限：8个种子、3跳无重复节点路径、最多50路径、40上下文来源；按稳定ID打破同分。
扩展来源使用相同RRF规则，A/B随后共用候选去重、P4渲染与统一回答模型/提示。
P4渲染最终上下文，结构也计入12000 Unicode码点，裁剪同步更新end/quote。

`exports/queries/query-<id>/retrieval.json`保存候选、真实底座命中、种子、路径及
回答器返回的最终context/run_id/usage；`result.json`保存QueryResult。
最终可见证据以回答器保存的context为准，不按图节点、截断前候选或最终引用替代。
答案展示仅连接claims.text；path证据可展示，但不能给未送入回答器的断言背书。
查询日志和回答缓存不进入sources/manifest。P6私有题目/参考不在本模块读取范围内。

## 验证

```text
P2_TEST_NEO4J_URI=bolt://127.0.0.1:17687 python -m pytest tests/test_graph_query.py -q
```

Windows PowerShell先用`$env:P2_TEST_NEO4J_URI=...`设置同一环境变量。
可选`P2_TEST_DATABASE_URL`指定专用Postgres测试库；缺省使用临时SQLite。
无Neo4j环境时集成测试明确skip。测试仅清理随机p2_test命名空间，不清全库。
2026-10-30已在macOS/Python3.11.15、实际Neo4j5.26.0/PostgreSQL16.4完成14项检查；
Windows实机验证及真实DeepSeek问答接收仍须后续运行记录。
