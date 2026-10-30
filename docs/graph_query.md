# 图谱导入与公共查询（P2）

接口契约1.4.2；兼容1.4.1冻结记录。本实现基于P4移植的relore和P1/P3/P4统一冻结记录。
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
实际relore数据库必须可读；load为每个数据集建立冻结检索空间，
Neo4j写完后读回所有记录并复算指纹。

### 1.4.2增量模式

实体集合在原有Project、Release、Issue、PullRequest、Commit、File、Decision上增加：

- `Developer`：GitHub账号身份。逻辑键为`identity_key`；当前P3重放分片写成标量
  `key=identity_key`，校验器同时兼容早期交接的单元素`key=[identity_key]`。有数字用户ID时
  `identity_key=github:<id>`，否则为`login:<casefold(login)>`；两种写法归一为同一稳定ID
  `entity_id("Developer", repo, identity_key)`，属性保留原文login/display_name及
  `github_user_id`，不把列表key当主体别名。
- `Function`：特定提交SHA和文件路径下的Python顶层函数。`key=[sha, path,
  qualified_name, start_line]`，稳定ID也包含`start_line`；因此同文件同名但起始行不同的
  重复定义是两个实体。方法/类归属不从函数名猜测。

关系增加`Authored(Developer→PullRequest)`、`Merged(Developer→PullRequest)`和
`Defines(File→Function)`。`Authored`来自PR JSON的`user.login`，`Merged`来自
`merged_by.login`；二者都描述PR参与关系，不表示commit作者，因冻结数据没有
commit author证据，不建立Developer→Commit。`Defines`要求Function与File的
commit_sha、path完全一致。Feature不新增；功能与模块边界由Decision/File表达。
旧1.4.1记录、实体和关系保持原语义，无需改写。

Neo4j约束为`HGDataset(dataset_id)`、`HGRecord/HGEvidence(dataset_id,id)`及新增
`HGDeveloper/HGFunction(dataset_id,id)`唯一。新实体仍继承`HGEntity/HGRecord`，
并附加对应类型标签，便于按dataset幂等导入和定向检查。
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
若P1主体目录尚未物化Developer/Function，查询层从当前dataset实体生成同等主体视图：
Developer按login/display_name/github_user_id等标量属性，Function按
qualified_name/name/path及`path::qualified_name`解析；不从`key`拼接别名。
返回路径仍使用已存实体，不创建临时图节点。

固定方法版本`relore_common_rrf_graph_v2`：先真实调用P4 `search_history`（10命中），
按P1 `relore_mapping`映射到本数据集来源；再对完整共同来源池使用固定词法适配，
包括讨论、code、release_note、commit_message、git_output、api_response。
词法为英语/标识符与中文二元词，标题加权，按得分降序、source_id升序；
两种排名通过`1/(60+rank)`合并。候选再按问题显式范围排序：Issue/PR编号且没有
代码路径或提交SHA时，优先issue_body、comment、review与pr_body，并降低通用API元数据；
问题明确给出代码路径或SHA时，优先origin_key同时匹配的code快照。该排序对A/B一致，
图扩展只用于同一直接相关层内的次级排序。来源原文始终取当前冻结包，不取其他数据集文本。
底座命中、映射及可见来源清单保留在查询日志，不能把适配检索称为纯relore原生排序。

讨论检索不会访问随后可变的全局repo索引。load从P1 manifest所指的P4 capture
回放ThreadPayload，对每个body/comment/review/review_comment按映射逐条核对C5冻结正文，
多出/遗漏原对象或文本不一致整批拒收。原始回放输入保存为
`exports/relore_input.json`，迁移/复现须随冻结数据包保留，可脱离旧capture绝对路径重建。
正式Postgres使用同实例中按dataset_id哈希生成的独立schema；SQLite开发模式使用
本数据集exports/relore_index.sqlite3。schema与源码层的真实relore仍保持不变。
图中只保存无凭据的索引描述符，query按该描述符访问且核验冻结输入指纹。
后续同repo构建更新全局index_payload不会改变旧dataset的命中、排序或文本。
无讨论映射的toy/纯代码包在空relore索引上使用共同来源适配，不冒称讨论命中。

`config['system']='A'`关闭图扩展，`B`为默认；两组共用问题解析、初始种子、
来源池和词法/relore排名。B仅沿当前数据集的真实关系扩展，不从图引入新原文。
当前界限：8个种子、默认3跳无重复节点路径、最多50路径、40上下文来源；按稳定ID打破
同分。已发布`relore_common_rrf_graph_v2`正式A/B仍固定按3跳。需要展示完整
Developer→PullRequest→Commit→File→Function时，调用方必须显式传
`graph_depth=4`；分支较多时还可显式把`graph_path_limit`从默认50提高至最多100。
若问答已经显式给出完整主体种子，验收还可设`graph_expand_seeds=false`，只从问题
解析/显式指定的种子出发，避免证据映射追加无关分支。这些只是4跳展示/验收配置，
不改变v2默认协议；正式A/B仍默认启用来源种子扩展。
扩展来源使用相同RRF规则，A/B随后共用候选去重、P4渲染与统一回答模型/提示。
P4渲染最终上下文，结构也计入12000 Unicode码点，裁剪同步更新end/quote。

`exports/queries/query-<id>/retrieval.json`保存候选、真实底座命中、种子、路径及
回答器返回的最终context/run_id/usage；`result.json`保存QueryResult。
回答模型记录默认写本数据集`llm/`，也可显式传answer_output_root或answer.output_root；
普通使用者不填写内部路径。QueryResult附usage/model_run_id供界面与实验记账。
最终可见证据以回答器保存的context为准，不按图节点、截断前候选或最终引用替代。
答案展示仅连接claims.text；path证据可展示，但不能给未送入回答器的断言背书。
查询日志和回答缓存不进入sources/manifest。P6私有题目/参考不在本模块读取范围内。

## 验证

```text
P2_TEST_NEO4J_URI=bolt://127.0.0.1:17687 \
P2_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:16432/historykg_course_test \
python -m pytest tests/test_graph_query.py -q
```

Windows PowerShell先用`$env:P2_TEST_NEO4J_URI=...`设置同一环境变量。
可选`P2_TEST_DATABASE_URL`指定专用Postgres测试库；缺省使用临时SQLite。
无Neo4j环境时集成测试明确skip。测试仅清理随机p2_test命名空间，不清全库。
2026-10-30已在macOS/Python3.11.15、实际Neo4j5.26.0/PostgreSQL16.4完成26项检查，
全套pytest为149 passed / 13 skipped，并对冻结检索、正常回答目录、真实P4渲染/截断
和路径显示补充回归。
Windows实机验证及真实Flask/DeepSeek问答接收仍须后续运行记录。

新增实体/关系回归覆盖旧1.4.1 fixture继续加载、P3形状的Developer/Function幂等导入、
dataset隔离、`Authored/Merged/Defines`端点、同SHA同路径Defines约束、同名不同
`start_line`函数身份隔离、错误key/ID与缺行号拒收，以及默认3跳不返回完整链、
显式`graph_depth=4`才返回Developer→PullRequest→Commit→File→Function。
设置`P2_REAL_P3_DATASET_DIR`后，回归还会读取P1冻结包与真实P3重放分片合并后的
完整数据，校验固定counts、实际标量Developer key、四元Function key，并实际加载
PR #6096的四关系路径。
真实P3分片为18 Developer、384 Function、20 Authored、4 Merged、384 Defines，
manifest的代码阶段本地model_requests=0（不计作整个历史生产抽取计数）。与P1冻结包
合并后的数据集`p2_p3_real_014e28d89e1f`有sources 370、
source_units 40、evidence 741、entities 535、relations 591、subjects 65；校验和加载均
成功，随机测试namespace中的显式4跳QueryResult为status ok、99路径、53 evidence、
0模型调用（run_id `query-0746f75077e84b6f8759782dd7a76d80`）。
生产只读dataset仍只有PR→Commit→File，没有Developer/Function。真实Flask #6096
跨源链、生产缺口及旧合成结果废弃说明见`evaluation/results/cross_source_chain.json`；
该文件不把派生验收链冒充生产图记录。
