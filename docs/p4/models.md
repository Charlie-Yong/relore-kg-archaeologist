# 共享模型通道、抽取和统一回答器

P4维护`historykg.llm`和`historykg.extract`。公共记录、ID和证据定位复用P1，
唯一构建编排仍为P1。生产凭据只读取`DEEPSEEK_API_KEY`；请求文件不保存密钥或认证头。
模型配置见[样例](../../config/model.example.json)。评审由P6显式提供独立配置和提示。

## 调用

~~~python
from pathlib import Path
from historykg.extract import run_extract_stage
from historykg.llm import answer_question, prepare_request, run_request, render_context

budget = {
    "ledger_path": "/deployment/.local/execution/deepseek_budget.sqlite3",
    "approved_cny": 10,
    "max_cost_cny": 10,
}
result = run_extract_stage(Path("data/dataset"), config=model_config, budget=budget)
answer = answer_question(
    dataset_id=dataset_id, repo=repo, question=question, context=ranked_fragments,
    config=model_config, budget=budget, output_root=Path("data/dataset/llm"),
)
~~~

本轮六角色只用主部署的**同一个账本绝对路径**，不能每角色、每dataset另开10元。
配置中的上限非空检查不能代替此共享账本。本机路径由主代理私有运行配置提供，
不写入公开样例。数据库以整数微元记账，`BEGIN IMMEDIATE`先保留请求上界，再发送。
输入用完整消息UTF-8字节数加4096聊天封装余量作为保守token上界，输出用`max_tokens`；
重试反馈也增加预留。发送前仍用Flash输入cache miss 2元/百万、输出8元/百万的高峰
费率预留。收到完整usage后，按服务报告的缓存命中/未命中与实际请求起止时间结算：
Flash高峰命中0.04、未命中2、输出8元/百万token；空闲分别0.02、1、4元/百万token。
北京时间周一至周五9–12、14–18为高峰，其余空闲；未额外假设法定节假日优惠。
跨时段或起止不明用高峰；缓存字段缺失/不一致把输入全计未命中；必要用量不全与未知
HTTP结果继续占原预留。金额用Decimal逐attempt向上取整到微元。所有失败与重试均留账。
`attempts.settlement_json`保存价格、时段、token细分和官方依据，不参与run_id或请求身份。
已固定上限不能通过
新实例提高；`lower_ceiling()`只允许降低有效上限。2026-10-30用户追加10元后，主代理
本地审计文件`.local/execution/budget_extension_20261030T072516Z.json`记录授权上限
由10元扩展为20元、有效ceiling为19.84元，历史费用未清零；当前本地审计余量为
11.466488元。此前165次历史尝试的原子对账仍保留在账本与
[历史核算摘要](../../deliveries/P4/2026-10-30/budget_reconciliation.json)中，
不能把旧快照的1.466488元余额继续当作当前余额。本轮最终回答链审计没有新增模型请求。

费用报告以共享账本`attempts.charged`为当前核算额；可按task/state或明确的attempt_id聚合。
`snapshot()`另给`accounted_cny/known_usage_cny/unknown_upper_cny`。既有不可变缓存中的
`charged_upper_cny/charged_micro_cny`保留原高峰上界作历史说明，不代表对账后当前核算额，
不能把缓存旧费用相加当provider账单。新调用结果中的同名字段反映本次核算且仍含未知上界；
缓存回放`new_charge_upper_cny=0`，不新增费用。公开报告分列已知核算与未知上界；私人账户余额变化只留本地审计。

网关记录四种task：extract/answer/reference/judge。`prepare_request`参数为
`task,dataset_id,payload,config,prompt,prompt_version,output_schema,output_root,repeat_index`，
均为关键字参数。`run_request(request, *,budget,validator=None)`执行并返回
`status,run_id,parsed,attempts,usage,cache_hit,new_requests,budget`。
支持生产Schema用到的type/required/properties/enum/anyOf/本地$defs/minLength/minItems；
P6有额外语义约束时传`validator`，失败保存并有界重试，不静默改写响应。

run_id覆盖任务、dataset、规范输入、实际配置、完整提示、提示版本、Schema与repeat_index；
切换thinking/输出上限/提示会产生新run_id。输出位于
`<output_root>/<dataset哈希>/<task>/<run_id>/`，含request、每次attempt的真实request/response、
record、parsed及最终result。attempt后缀0–2，最多3次发送。HTTP成功但finish_reason非stop、
空输出、JSON/Schema/引文失败都不算成功。单run使用操作系统文件锁避免并发重复发送；
进程退出后可恢复未结束run，已经保留但未收到记录的尝试继续占预算并消耗一次重试。
预算暂时不足保存blocked快照，可在其他并发请求结算后恢复；不会把blocked缓存成成功。

**reference/judge从prepare阶段起强制显式private_test路径**，生产任务拒绝该路径。
P6必须传自己控制的`evaluation/private_test/...`输出根；私有请求、原文组合、原始输出、
缓存及评分不进入共享data/llm。P4未读取P6测试内容；本模块的合成隔离测试不是真实参考实验。

## 抽取

`run_extract_stage(dataset_dir, *,config,budget)`读取sources/source_units/subjects，
返回status/artifacts/counts/gaps/usage/model_run_ids。输出`p4/{decisions,entities,relations,
evidence,candidates,failures,coverage}.jsonl`及result.json。`actual_llm_extraction`仅在模型
成功返回结构化结果后为true；0条Decision可保留真实空结果，模型失败不伪装为空。
partial/unread源单元和未处理分块记录覆盖缺口；长文本按码点分块、400码点重叠，
完整覆盖清单和每块run_id留档。来源不静默截断。

候选必须选同repo目录中的现有主体；无唯一主体留unresolved，外库改动留external_project，
均不生成Decision/ABOUT。候选保留target_repo、归属、结论、理由的原始引文。
明示理由单独填rationale和理由证据，即使statement已提及原因。quote按P1
make_evidence定位；重复引文必须有offset或邻近上下文，不能任选一次。校验同时限制
引文在本次可见块内。有效Decision通过公共decision_id赋ID，Entity与ABOUT/EVIDENCED_BY
确定性派生。源码引用存在仅证明定位正确，语义质量仍待P6独立评审。
空白statement、空白rationale和只含空白的证据quote在Pydantic边界直接拒绝，不进入
候选文件或Decision派生；证据原文中的空白本身不能充当结论依据。

## 回答与最终上下文

`answer_question`仅返回带证据的claims、C5 evidence及gaps/run_id/usage；无summary/answer。
status为ok/empty/error，运行失败单列error和model_status，不能当成正确弃答。
P2装配QueryResult及paths。最终正文只能连接全部claims.text。

context每项为`source_id,start,end,quote`，可附dataset_id/repo/title/url/author/time。
调用方应来自已校验冻结来源。`render_context(context, *,max_characters=12000)`保留候选排序、
去重，在句/行边界裁剪并同步end/quote，返回fragments/rendered/characters/gaps。
characters为实际送入prompt的context数组规范JSON的Python len，包含标题等结构字段；
问题与系统指令另存。answer保存候选及最终context.json供P6按最终可见区间复算召回。
模型只输出逐字quote，程序计算码点偏移；不要求模型猜数值位置。重复quote需扩大到唯一
原文，无法定位的claim使该次请求失败，最多2次重试后返回error，不悄悄丢掉断言。
claim正文、弃答gap和证据quote的纯空白值都在Schema边界拒绝；没有证据的claim不能通过。
若两个上下文项具有相同source_id/start/end但quote不同，渲染直接报不一致，不采用先到先得。

`Developer`、`Function`等新增实体和`Authored`、`Defines`等新增关系属于P2的路径数据，
answerer不枚举类型，也不把路径标签当作事实证据。`render_context`只读取冻结来源的
source_id/start/end/quote及标题、URL、作者、时间等白名单字段；未知或新增的路径元数据
会被安全忽略，不会改变最终可见片段。路径本身由P2保留在QueryResult.paths，界面按
entity.type、relation.type和properties.display_name/key做通用展示；因此新类型无需新增
模型调用。若同一冻结来源的同一偏移出现不同quote，仍按上文判为数据不一致。

## 当前实测与复现边界

2026-10-30最小真实请求返回model=`deepseek-flash`，thinking明确disabled，82输入/5输出。
官方文档映射版本为DeepSeek-V4.1-Flash-1017；响应仅返回别名，不能声称响应给出了完整版本。
开发旧试跑主题6133的新抽取与回答记录见[P4交接](../../deliveries/P4/2026-10-30/handoff.md)。
缓存重放不发新请求；修改提示后的实际效果单独用新真实请求验证。P6正式冻结实验已完成：
测试集抽取Precision/Recall/F1为0.568/0.962/0.714，理由覆盖13/15；A/B事实覆盖为
0.600/0.740，配对差0.157，但bootstrap区间[-0.122,0.457]跨零。共享账本当前授权
20元、有效上限19.84元，历史已入账8.373512元；追加后的本地审计余量为11.466488元。
逐项分母、限制和复算入口见
[正式汇总](../../evaluation/results/formal_summary.json)与
[P4最终验证](../../deliveries/P4/2026-10-30/formal_validation.json)。

2026-10-30最终回答链无费审计使用公开冻结Flask包完成一次
`prepare_query`与`render_context`：包指纹与共享图库一致，37个候选、40条路径，
最终6个片段、11972/12000码点、32个裁剪gap，新模型请求0。该检查只验证接口和证据渲染，
不是回答质量实验；实际冻结数据尚未包含Developer/Function/Authored/Defines，新增类型由
合成兼容测试覆盖。机器记录见
[最终回答与渲染审计](../../deliveries/P4/2026-10-30/final_answer_render_audit.json)。

核对的原始文档（2026-10-30）：

- [Chat Completions](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)：POST /chat/completions、JSON模式、max_tokens、finish_reason。
- [思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)：thinking.type=disabled/enabled，默认开启，因此实际请求显式关闭。
- [模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：型号映射、缓存命中/未命中与北京时间峰闲计价。
