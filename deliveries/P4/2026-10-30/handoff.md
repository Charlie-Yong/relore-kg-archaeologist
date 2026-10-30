# P4 共享模型与结构化抽取交接

日期：2026-10-30，契约1.4.1，分支feat/p4。本轮新增实现由P4角色AI完成；P4前期独立调研、方案、原型、移植及基础接口的成员贡献继续引用[原记录](../2026-10-27/handoff.md)。

## 讲解与边界

主代理在本轮先向成员发送了C0完整项目原理说明；P4角色AI完整读取工作单、AGENTS、STATUS、既有handoff、试跑记录及collector文档后，实施前向主代理发送了具体输入、处理、输出说明，由主代理负责面向成员协调。这是实际发送方式，不冒称P4直接向成员发送或成员已确认理解。

P4接收P1冻结的sources/source_units与P1/P3自动生成的subjects；模型生成候选后，程序校验同repo现有主体、项目归属、理由字段及Unicode码点引文，外库和无法映射候选留账。回答器消费P2最终上下文，只返回claims和证据。P1拥有唯一build流水线，P2拥有QueryResult，P6私有参考不进入生产开发。

## 首批：采集器接入及续作

已接收公共首批e0f4ab2，普通merge feat/p1。collector增加selected、resume_capture、initial_requests、initial_http_responses、profile_version，详见[接口说明](../../../docs/collector.md)。底层复用完整线程和成功分页，保留Link及冻结请求计数，不把回放计作新请求。

实际验证：使用主仓库既有Python3.11环境，显式`PYTHONPATH=vendor/relore:.`使import指向本副本的vendor。doctor返回bundled=true。38项当前P4测试通过（其中collector含SQLite和PostgreSQL两后端），命令：

~~~text
PYTHONPATH=vendor/relore:. RELORE_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:16432/historykg_course_test <venv-python> -m pytest tests/test_llm.py tests/test_extract.py tests/test_collector.py -q
# 38 passed in 1.62s；尚未代表P1接收验收或整系统完成。
~~~

后续批次持续更新本记录；正式实验与URL自动闭环待接收方实际运行。

P1接收首批后指出末尾写capture无法恢复进程中断。已补每次请求前/每个响应后/线程完成后的原子checkpoint；在第7个请求模拟KeyboardInterrupt，累计耗用7、收到响应6、完整线程1均在磁盘，随后恢复到2线程成功。相关collector双后端30项通过（1.45秒）；这是真实异常分支回归，无付费请求。

## 模型、抽取、回答器提交

普通merge公共83aba79后，使用同一contracts/ids/io完成：

- `historykg.llm.prepare_request/run_request`四任务网关，显式thinking/max_tokens、实际model、finish_reason、reasoning_tokens、原始响应、失败、最多2次重试、输入/提示/Schema/config哈希及repeat_index缓存。格式/引文失败的反馈和实际重试请求逐次保存。
- SQLite全局预算事务先保留UTF-8输入字节上界+封装余量与max_tokens，再发请求；失败未知用量占原上界，实际usage按保守高峰费率结算。所有角色共用一个账本，账本已固定授权不能被实例重置；账户余额只可降低有效ceiling。OS单run锁防重复发送，进程中断后已耗尝试也占用最多2次重试，预算暂缺不会被永久缓存。
- `historykg.extract.run_extract_stage(dataset_dir, *,config,budget)`读取P1/P3已有主体，保留全部候选/归属/失败/coverage。外库和unresolved不造Decision；明示理由须单列。引文同时检查P1源码点偏移和实际可见块。Decision节点及ABOUT/EVIDENCED_BY由有效记录确定性派生。
- `historykg.llm.answer_question`与公开`render_context`：唯一的最终上下文渲染、排序保留/去重/句边界裁剪/12000码点上限，只返回claims和C5 evidence，无summary。模型只交quote，程序唯一定位，禁止让模型猜数值偏移。P2装QueryResult并负责paths。
- [模型配置样例](../../../config/model.example.json)、[调用及预算说明](../../../docs/p4/models.md)、[脱敏开发验证与请求哈希](model_validation.json)。生产extract/answer与P6显式提供的reference/judge配置分离；评审任务从prepare阶段要求P6控制的private_test路径。未读取P6私有内容。

## 真实开发请求、失败及费用

本机安全定位的旧OpenCode凭据对官方API返回401，未循环重试，保留未知扣费上界0.009858元。随后仅只读本人既有CC Switch DeepSeek配置，在进程内置DEEPSEEK_API_KEY；官方/user/balance为200。没有新建/更改凭据，没有输出值。生产程序仍只读环境变量，不依赖这台机器的配置路径。

最小真实请求：run `200e0ba7d8af2fbc067f4af3396fa3b9e0602ba89b45fa071ffe3f07347cfcf1`，实际model=`deepseek-flash`，thinking=disabled，82输入/5输出，stop。官方文档映射版本DeepSeek-V4.1-Flash-1017，响应本身只给别名；不虚构完整版本字段。

开发主题为已知旧试跑PR6133，仅复用旧冻结pr_body/API原文并重建C5记录，不是新采集或URL无人验收。未重新核对完整讨论，单元明确partial。原失败抽取run `68c89025be7556e5292d5e8a40afe9420303f96762d61bc4c62bc2f781bb1be6`：模型已抽出明示理由、正确区分外库，但额外的full_name归属引文重复，2候选被拒收。改提示与自动引文校验后，实际新run `de39d7a5a7f58d30b5c4eecec627f507ee51f543c5e8328b0fff9fe4427bc86e`得到2条本地Decision、1条external_project候选、0候选失败。2条本地Decision均有stated理由；Werkzeug client.query未挂本地。公共validate_dataset为ok：2 sources、3 entities（含PR）、5 relations、6 evidence。

真实回答旧run `69cd2f74139959a8d3e54032584cefc7663ee11416e6fe0dacc05514a9ad4b23`有3次尝试，因模型猜错数值偏移均失败，未把空claims当弃答成功。改Schema让模型只交quote后，新run `17c1e34047352702632cae4cdae17fccc7e251606920770aa241ec2452d6bb0c`真实返回2条claims、2条可定位证据：本地测试调整因Werkzeug未发布；client.query属于Werkzeug。偏移282–352、204–281按源码点定位。旧原始响应/失败仍留各自run目录，未覆盖为成功。

所有原始记录在P4工作副本`.local/p4/`，开发数据根`.local/p4/dev_regression_6133`，模型文件清单哈希及真实调用明细见model_validation.json。随后删除API环境变量运行相同抽取与回答，均缓存回放成功、新请求0；这不是第二次在线验证。

本轮截至交接：8次真实尝试（7次有usage、1次401未知），7次按高峰保守估算0.070722元，未知上界0.009858元，账本累计0.080580元，非实际账单。授权10元、已固定effective cap为9.84元，余9.759420元。所有后续角色以同一实时ledger为准。余额前/后快照与凭据来源元数据仅在主部署`.local/execution/`，没有密钥。全部费用含失败及3次失败回答，不能只报成功请求。

## 检查与接收恢复

最终检查：`python -m ruff check historykg/llm historykg/extract tests/test_llm.py tests/test_extract.py tests/test_collector.py`通过；使用上列PYTHONPATH与专用Postgres配置运行`python -m pytest tests -q`，**57 passed in 1.56s**。其中跨进程预算竞争、四task隔离、未知费用、中断续试、same-run锁、length不算成功、理由漏填/外库/无法映射、所有claim引文、最终裁剪均覆盖。Windows分支代码已提供，尚未实机验证；不把macOS通过当Windows通过。

P1：merge feat/p4，已有job沿用来源进入extract，无须重新采集。config直接用model.example.json顶层dict；budget传`ledger_path=<唯一主部署绝对路径>,approved_cny=10,max_cost_cny=10`。本机账本位于主仓库`.local/execution/deepseek_budget.sqlite3`。接口usage含actual_llm_extraction/new_model_requests/cost_cny；cache回放费用不作新费用。

P2：直接导入answer_question与render_context(context, *,max_characters=12000)。提供source_id/start/end/quote及可选元数据，复用返回context作为实际prompt召回口径；evidence含完整C5字段及url/author/time。回答器返回new_requests/cache_hit，usage.new_charge_upper_cny区分新费用与历史run总用量。不要另建回答提示或summary。

P6：只在自己的private_test根使用reference/judge；同一ledger，不直连、不拆分每人10元。该主题明确dev，不能计入正式盲测；完整正式参考、评审和质量指标仍未执行。本轮合成回放与工程测试不替代独立模型参考。

阶段为ready_for_integration，接收方实际流水线与独立工程复核待完成，P4整体角色未done。按C3.3本轮日常实现自检不新开独立付费审查；主代理负责集成阶段复核。P4下一恢复点是已有job的extract/answer联调失败，不扩大为其他角色模块。


## 预算核算接缝修复与一次历史对账（2026-10-30 13:28 北京时间）

沿用本记录已有C0讲解发送记录；恢复后读取AGENTS、handoff与实际预算/网关代码，先向
主代理说明修复责任，再普通merge本地main至6d1c514。仅修复计费结算与审计；模型、提示、
温度、输出上限、重试、run_id/请求身份及缓存不变。未读取P6私有提示、参考、预测或原始响应，
只用共享SQLite token用量、公开model_id与各角色提供的非敏感完成时间证据；本轮新模型请求0。

故障是将全部已报告usage按高峰cache miss结算，过早占满账本。发送前仍用相同峰值未命中
上界预留；新结算按官方cache hit/miss与完整调用区间选费率，跨时段/时间不明选高峰，缓存
字段不完整按全部miss，必要用量不明仍保留预留。金额Decimal逐attempt向上取micro。
`settlement_json`保存依据；SQLite并发预留/结算仍以BEGIN IMMEDIATE事务串行。

历史对账持有写锁先用SQLite backup留原账本，再一次事务更新已知费用并留165条old/new、
原reserved及价格依据。164条已知usage统一被实际完成时间上界2026-10-30T00:01:11Z覆盖，
均明确空闲；1条401未知0.009858元保持原账。核对元数据逐字段不变、账本integrity_check=ok，
cap=10000000与ceiling=9840000微元均不变。对账前9.566638元，对账后3.780790元
（known=3.770932、unknown upper=0.009858），释放原预算未用部分5.785848元，余6.059210元。
精确token金额3.77085592元，逐attempt向上取整加0.00007608元；私人账户余额与
精度核对仅留主部署本地审计，不纳入公共报告。
公共数据详见[核算摘要](budget_reconciliation.json)；原备份和完整本地审计位于主部署
`.local/execution/deepseek_budget_before_reconciliation_20261030T052804Z.sqlite3`及
`.local/execution/budget_reconciliation_20261030T052804Z.json`。

旧缓存费用字段继续表示历史高峰上界，公共报告分列共享账本当前核算与unknown upper；
私人账户余额变化只留本地审计。P1/P6按明确attempt_id读取`attempts.charged/settlement_json`聚合，
不要用旧result/record费用覆盖或推导账本。所有调用方需先merge本次新代码，再恢复请求；
本轮不重打模型、不重抽取来源。该次历史修正幂等，重复执行只返回已存审计摘要。

验证：`ruff check historykg/llm tests/test_llm.py tests/test_pricing.py`通过；
`pytest tests/test_llm.py tests/test_pricing.py tests/test_extract.py`34项通过（无付费请求），
覆盖cache hit/miss、Decimal取整、峰闲/周末/午间/跨边界/未知时段、缺字段保守、网关保留
原预留但按新策略结算、备份/old-new/幂等、unknown不降低、原cap不变及活跃请求禁止历史对账。
额外运行graph_query测试时15项因未提供外部数据库配置跳过，不冒称该集成通过。

Planning checks通过（文档及本地链接），不代表正式实验完成。


## 同语义上下文裁剪性能修复

P6与主代理在公开dev检索后独立复现：大API JSON进入render_context后，原算法对大量
句/行边界反向逐一canonical序列化，CPU满载且超过130秒。根授权P4修复这个具体接缝。
现在利用JSON前缀长度单调性，对相同的合法边界二分寻找最长可容纳前缀；排序、去重、
完整句/行边界、quote/end、gaps与12000码点计数均保留，prompt/config/run_id未变。

实际公开dev-01/A共40候选、最大quote 1,811,025码点，新算法耗时0.056秒，得到11983
码点、4 fragments、38 gaps；只读取正常开发检索候选，不含private_test内容。
500组含Unicode、JSON转义、重复span、排序及不同预算的小样对照旧算法，完整输出
canonical逐字相同，摘要见[无费回归](render_context_regression.json)。单元测试另约束
大JSON的序列化次数为边界数对数级，并核验下一个完整边界确实超预算。

最终相关检查：Ruff通过；pytest llm/pricing/render_context/extract共41项通过。
本轮仍无模型请求。公共资料仅保留实验费用与预算上限；账户余额前后值及精度核对仅在
主部署本地审计中。当前公开交付分支为feat/p4-budget-render-public，基于已共享main前缀
生成清洁提交，不包含本地含私有余额的预算草稿提交祖先；本地私有ref保留原审计历史。
