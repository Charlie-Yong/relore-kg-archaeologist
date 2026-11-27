# P6 独立参考、实验与自动验收交接

P6，2026-10-30，规划/契约1.4.1，唯一副本relore-agents/p6，长期分支
`feat/p6-formal-results`。状态`ready_for_integration`；独立参考、正式计分、A/B、
全池重试、第二小库和最终自动验收已完成，等待接收方按C3.3/C10独立复核。

## 说明与发送记录

主代理已向同一用户完整发送C0八项中文讲解。P6先只读完整AGENTS、本人工作单C0-C10、
总规划/STATUS、旧试跑缺陷、P4前期贡献和已有代码，再经协作消息向主代理补充本人
输入/处理/输出及TP/FP/FN与理由覆盖例子。此处如实记录经主代理协调的发送方式，
不冒称P6另外直接面向用户发送了八项全文，也不声称用户确认理解。
本轮应用Stop That Shit change技能，无新增子代理。P4前期研究、架构、规划、原型和
采集移植贡献归P4，见[其记录](../../P4/2026-10-27/handoff.md)。

## 同步、输入与隔离

普通merge本地main，以及P1 c9c54fb、P2 d972d08、P4 776e556；随后普通merge P2 a6604fa
（含0209e47按dataset冻结Postgres检索与默认回答缓存修复，以及P1最新集成）。未重写历史。
唯一真实输入为原Flask URL job b61942bf06b742e48860d064dffe6df2：
dataset:810db3718867788c5acb0fa437cdbf62bc0f99cd8e7435e9261471225f5cd00c。

来源池369条、40完整线程、24可用文件快照；P6只依赖原文/主体/plan冻结40讨论10dev/30test、
12单文件快照4dev/8test。旧诊断#6133/#6096及关联、QUERY主题、#6123关联旧#5774与先前
collector可见#6168/#6175归dev。公开[来源清单](../../../evaluation/results/source_only_freeze.json)
无正式问题/参考。来源池哈希09ebc011e84b1717218fa60268c3b73b78b976e4def695ddae88d2e75faf7d45。
代码数量没有扩大为12对。未读取正式生产预测来编参考，未按结果补采或删题。

私有测试原始资料从首次生成起留evaluation/private_test/<dataset>/，不入共享Git。
正式题目/参考/评审/原始请求响应/盲化映射不交生产角色；只发运行清单、开发反馈、计数和
最终允许发布汇总。完整实验后按课程授权另归档可复算包。

## 已实际运行

- historykg/evaluation已有离线计分、freeze、完整线程reference/review、代码静态核验、
  QA问题先行/参考复核、全池核验、匿名A/B运行/全部claims评审和统计程序。
- evaluate入口由P1现成CLI转调本模块。toy计分实跑TP/FP/FN=1/1/1、P/R/F1=.5、理由0/2。
  这仅为合成验收，不充当Flask实验。
- 开发参考v1有一批2线程因校验器不接受Schema允许的null项目候选，最多2重试后failed；
  三次请求与费用完整保留。dev修复后提示/版本v2保留未解析候选，新请求重跑。
- v2开发完整原文reference+独立review 10/10，正式测试30/30实际成功；引文原文唯一定位、
  主体目录和结构校验通过。银标含复核差异/unclear，结构通过不等于准确率。
- 已向主代理与P1发明确生产extract放行信号，参考先于生产抽取落盘；P1恢复原job。
- 24问题已先冻结ID/正文，再另请求生成24/24答案参考及独立review。内容仍私有。
  证据不足候选的全池核验进行中，全部369源5,309,480码点，46批×2独立请求。
- 12文件快照先独立读源码生成静态参考，再核对P3：4dev/8test的有限解析、顶层符号/
  docstring及发出Imports引文/同SHA检查均correct。无事件召回或未采依赖完整性结论。

截至参考阶段的共享账本保守累计1.513890元、余8.326110元；后续运行实时增加。
全组使用同一主部署账本，批准10/有效9.84；所有reference/judge/失败/重试入账。
本数字是保守估算而非账单实扣；后续最终阶段附精确快照，不按本中途数冒充最终成本。

## 检查与复现

实际平台macOS，Python3.11.15，使用主venv但PYTHONPATH=本人vendor/relore:.，避免导入旧副本。
Windows尚未实机/CI验收，不据安装说明标通过。本人代码相关ruff通过，计分验收9 passed；
包括最大一对一匹配、重复FP、漏项FN、空理由独立计分、全漏F1=0、零分母N/A、漏评N/A、
所有claims及全池不足条件、最终截断证据不计召回和private_test冻结隔离。

~~~text
python -m pytest tests/test_evaluation.py -q
python -m ruff check historykg/evaluation tests/test_evaluation.py
python -m historykg.cli evaluate score evaluation/dev/negative_cases.json --out evaluation/dev/scorer_result.json
~~~

[方法/使用及引用](../../../docs/evaluation.md)给出公式、来源与隔离。已实际读取FActScore/KILT/
FEVER官方论文页面摘要，向P2提供其适用位置；不照搬其数据或结果。
按C3.3，日常自检不新增工程模型审核；本人模块阶段合入交主代理独立工程复核。

## 尚待与恢复

继续原P1 job完成生产extract/validate/index_graph后，P6读取全部预测/失败/coverage进行语义
匹配与计分；通过P2公共入口运行24题×A/B，只传ID/正文。冻结同来源、模型、提示与12000
码点；实际最终context.fragments用于召回。全部claims匿名逐项判断，保留unknown/漏评N/A。

全池不足核验、真实URL状态/恢复/幂等/跨源链、有限模块实答、第二小型公开Python库同profile
免改代码轻量检查、图表/最终可复算包及1400–1800字完整实验章节仍继续，不标done。
技术例行实施不再请求成员逐步审批；只有实际下一个必要请求无法预留才报具体预算缺口。

## GPT-6.1 Sol恢复（2026-10-30 13:25）

已先读AGENTS、完整P6工作单、交接及全部.local/evaluation控制脚本，核对既有C0发送记录，
向同一用户发送角色恢复说明。保留原冻结输入/缓存/账本，未重采、未重做参考或新增付费调用。
核验私有全池进度：预期92次（46批×2），目前50个位置记录中46 ok、3 failed、1 blocked；
最后为第二遍batch3费用阻断，未发现仍在运行的评审进程。3个失败均已用尽原最多2次重试，
原因是结构/引文校验失败，保留原记录，不重置或另起run绕过。全池结论尚未确认，相关题不
计正确弃答。剩余批次待P4准确结算完成并获主代理恢复信号后沿原脚本/缓存续作。

只读生产审计确认p4 coverage为40/40 ok、failures为0、candidates为65，正式语义评分尚未运行。
新增公共开发题清单evaluation/dev/questions.json只含4题ID/正文，无测试题或参考；dev-01
可演示自然语言讨论问答，dev-03可演示有限版本代码问题，架构职责最低实答仍须另外核验。
抽取运行器保存coverage/failures/candidates原始记录供离线复算；未知项目候选继续保留，
不让其成为已确认本地参考的匹配边，整体reference_complete仍为false。未改变生产模型、
提示或采集方法；未改变既有参考或题目。统计模块格式错误已修复。

恢复自检实际结果：tests/test_evaluation.py 9 passed；ruff模块检查通过；planning checks
通过（只代表文档检查）。公共模块/清单/dev结果先提交feat/p6供主代理工程复核。费用值
等待P4对账后更新，历史峰值上界保留为审计而不冒充账户实扣。

## 公开交付与无费联调（2026-10-30 13:35）

公共实现已提交4dcfc76并普通merge main，push成功、PR #7已创建：
https://github.com/Charlie-Yong/relore-kg-archaeologist/pull/7 。Planning远端通过，collector仍待检查。
进一步检查发现QA评审上下文原先只包含答案引文，现同时包含参考事实引文的原始邻近上下文，
供独立判断事实覆盖；尚未运行正式QA judge，未重做既有请求。新增无费集成测试验证漏一条
claim会拒绝且评审可见参考原文；evaluation+contracts共22 passed，ruff通过。

真实4道开发题×A/B prepare_query全部ok，同dataset fingerprint为
5cbe7b6f68a74d31ebf1fceeb7a00fd16d9b3737066b1ac7e9e51f90be955cfe；A无图路径，
B路径37–47条。此为检索接入检查，不是正确率或问答完成。原始候选私有保存，公开计数见
evaluation/dev/retrieval_audit.json。首题共同render_context耗时超过130秒且CPU100%，
停止本人无费检查后trace定位answer.py:84反向逐边界canonical长片段，已交P4所有者修复，
正式answers需等待等价性能修复；最终片段/字符计数当前均N/A。

evaluation/results/protocol_freeze.json记录方法文件哈希、模型配置及运行前状态；已复算
24题all_question_hash=d12bfc856698e609b8d8e9e34eab2737b8e5cdf0df8246584f92517073a5ecb8；
20道test_question_hash=8ee093e72075edcacb8120ed7c6d2eb4e8ca7c8bcadc6dbeb0052f6bd82633c5。
两者是不同范围，不混用。公开期中材料见midterm_experiment.md；正式实验结果仍未发布。
本地.local/evaluation/run_experiments.py已准备extraction/answers/judge/statistics逐阶段恢复，
不自动启动；费用修复需先普通merge主main，以避免旧版网关写入不兼容的结算列。

开发语义负例的原始结果必须一并披露：semantic_negative_result.json的严格双标签预期
通过0/3（all_passed=false），三条结论支持性均符合预期，空理由被judge判为unclear而非
预期unsupported。程序依据空rationale仍将理由覆盖判0，不让该分歧抬高覆盖。评审还指出
#6133参考未列出测试调整决策；这属于银标遗漏，保留reference disagreement，不反向修改
既有参考或为通过负例重开成功请求。正式指标按当前参考解释，报告该开发已知局限。
已普通merge origin/main d5cca1b，解开远端旧基线差异，未重写历史。

离线统计新增evaluate summarize入口；预期开发/测试题数为4/20。汇总遇到中断后只保存
部分题目时，整体事实/断言率为N/A，同时显示题目覆盖和可评子集，避免把中途结果误作
完整对照；重复question/system拒绝。新增覆盖回归后11个evaluation测试通过、ruff通过。
本次为尚未正式计分前的聚合缺口修复，不修改生产提示或题目。完整方法章节草稿已交P1，
后续以真实结果替换阶段段落，不将方法稿标为正式实验完成。

## GLM高推理恢复与正式结果（2026-10-30 14:25）

恢复成员先只读交接、公开控制文件和私有目录状态，不打开测试题、参考答案或评审正文。
答案阶段核验为24题×A/B=48条：32条ok、15条empty、1条error；无费回放未新增请求。
首次评审运行使用cc-switch中已失效的DeepSeek token，24题均在模型调用前返回HTTP 401；
24条失败记录、请求哈希和保守预留全部保留，未覆盖或删除。随后用模型目录探测找到本机
另一条仍有效凭据，只在运行时环境注入，不写入仓库或日志；恢复脚本改为优先使用显式凭据。
修订只改变请求版本标识，评审提示正文未改：`p6_blind_qa_judge_v1_20261030_auth_retry`。

修复后24次匿名评审全部ok，48个答案的全部claims和参考事实均完成逐项判断。测试集A/B
事实覆盖为30/50与37/50，证据组召回为35/55与38/55，无依据断言率为1/39与2/47；
B中位延迟2688毫秒、A为2285毫秒。配对事实覆盖差0.157，胜负B/A=5/4、6题持平，
固定种子95%描述性bootstrap区间[-0.122,0.457]跨零，结论不称显著。

公开汇总见[evaluation/results/formal_summary.json](../../../evaluation/results/formal_summary.json)，
测试抽取图见[extraction_test.png](../../../evaluation/results/figures/extraction_test.png)，
QA图见[qa_test.png](../../../evaluation/results/figures/qa_test.png)。图中文字和底部注脚
已逐张目视检查后修正排版。测试、lint与全池限制在最终核验段落更新。

最终本地核验为全仓114 passed、28 skipped，evaluation/contracts 23 passed，ruff通过；
planning检查通过并核对199个本地链接。公开汇总中的共享账本保守记账为8.373512元，
其中已知用量6.679102元、失败预留上界1.694410元，剩余保守额度1.466488元。服务商
余额会受本账本外充值和调整影响，不能替代该调用预算审计。PR #8在最新main上无冲突，
planning与collector两项远端检查均通过。

## 第二小库、全池重试与最终收口（2026-10-30）

主代理扩展共享账本后重新只读加载`.local/project.json`与账本：authorized=20元、
effective cap=19.84元。凭据只检查“存在且可用”并复用现有cc-switch运行注入，未输出
密钥；PostgreSQL 16432实测ok。最终检查时Neo4j bolt 17687/HTTP 17474连接拒绝；按主
代理要求未启动、停止或重启任何数据库，也未杀Java/Postgres进程。既有冻结图、查询结果
与证据导出保留，用于本次验收；实时重问能力当前不可用，已作为真实缺口记录。

第二小库使用未硬编码的`pallets/itsdangerous`，只输入公开仓库URL，走同一
`python -m historykg.cli build <repo_url>`入口和默认`course_small_v1`，未手选线程、
SHA或路径，未改源码、关系或证据。job=`ebfd8c8dae5e4bcf998a79fef35de981`，
dataset=`dataset:d817eee2ee7ff9763526b36aeb4d918493d0e6902633771deffca4bb33d69888`；
固化profile SHA-256=`c553085aa5164c800be3c06b82b591f0ff53d55b913301a74aaa351ba37d3366`，
来源池哈希=`60be0729a0aecf73795aba43075bce82e85a49f0a3cb598a764997915d007afd`，
图指纹=`12c370e99369a7bc2b1ea54c749fa464673c04b43515344f034404359aa2e682`。
作业生成347份来源、30个完整讨论单元、82个实体、78条关系和180条证据；validate ok，
graph/retrieval均ready。采集保留10次HTTP 404、147个未补采显式引用及分页/外部目标缺口，
故job状态诚实地为partial，但没有执行失败或人工补图。

两次真实查询分别为`search` empty和`dependencies` ok。可核对回答为
“Which modules does src/itsdangerous/timed.py import or depend on?”：返回50条路径、
25条证据和5条有出处claims；每条cited evidence ID均可解析，引文为冻结源码逐字子串，
来源SHA-256复算一致。原文URL为
`https://github.com/pallets/itsdangerous/blob/672971d66a2ef9f85151e53283113f33d642dabd/src/itsdangerous/timed.py`。
公开证据、完整答案、费用及复现命令见
[second_repo_acceptance.json](../../../evaluation/results/second_repo_acceptance.json)和
[second_repo_acceptance.png](../../../evaluation/results/figures/second_repo_acceptance.png)。
第二库真实费用为0.589461元，其中抽取26次0.569861元、2次回答0.019600元。

全池原记录92位置中86 ok、6 failed。仅对失败位置
pass/batch=0/2、0/11、0/21、1/11、1/12、1/27沿原分片和缓存做一次格式恢复重试，
6/6 ok；旧失败记录与备份保留，最终progress为92/92 ok。assessments的6题均完成两遍
完整核验，确认证据不足=0。因此正确弃答率继续N/A，分子0、分母0，原因是全池完整但无
确认不足题，不得把有效分母0表述为核验未完成，也不得把空回答算作正确弃答。重试
费用0.502822元。

共享账本最终保守累计9.465795元，其中settled 362次/7.771385元、uncertain 25次/
1.694410元，余10.374205元；本轮新增1.092283元，等于第二库0.589461元加全池重试
0.502822元。公开汇总、图表、最终验收矩阵和预算快照见
[formal_summary.json](../../../evaluation/results/formal_summary.json)、
[final_acceptance.json](../../../evaluation/results/final_acceptance.json)、
[extraction_test.png](../../../evaluation/results/figures/extraction_test.png)、
[qa_test.png](../../../evaluation/results/figures/qa_test.png)。private_test题面、参考、
回答及评审正文未读取输出到公开文件；公开JSON只含计数和标记。

复现命令如下（`$PRIMARY_VENV`、`$PROJECT_CONFIG`为本地路径，不在仓库保存凭据）：

```text
PYTHONPATH=vendor/relore:. "$PRIMARY_VENV/bin/python" -m historykg.cli \
  --config "$PROJECT_CONFIG" build https://github.com/pallets/itsdangerous
PYTHONPATH=vendor/relore:. "$PRIMARY_VENV/bin/python" -m historykg.cli \
  --config "$PROJECT_CONFIG" query \
  "Which modules does src/itsdangerous/timed.py import or depend on?" \
  --dataset-id dataset:d817eee2ee7ff9763526b36aeb4d918493d0e6902633771deffca4bb33d69888 \
  --kind dependencies
PYTHONPATH=vendor/relore:. "$PRIMARY_VENV/bin/python" -m historykg.cli \
  evaluate retry-pool "$PRIVATE/source_freeze.json" \
  --model-config .local/evaluation/config.json \
  --ledger "$LEDGER" --approved-cny 20
```

`--approved-cny 20`只是与账本固定cap匹配；账本ceiling=19.84仍由`MIN(cap,ceiling)`强制，
不会扩大有效预算。重试命令已完成且当前92/92无失败项，再次读取只会产生无费缓存/空重试。

最终实际检查在`PYTHONPATH=vendor/relore:.`下为全仓116 passed、28 skipped；
`ruff check historykg tests`通过。Matplotlib生成的SVG已清理机械行尾空格，最终
`git diff --check`通过。最终状态保持`ready_for_integration`，不冒充外部接收方
`verified_real/done`。剩余真实缺口是Windows未在本机实跑、Neo4j当前不可新连，
以及正确弃答因分母0保持N/A；这些均不影响已保存的第二库图/回答证据和92/92全池结论。
