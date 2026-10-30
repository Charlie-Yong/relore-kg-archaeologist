# P6 独立参考、实验与自动验收交接

P6，2026-10-30，规划/契约1.4.1，唯一副本relore-agents/p6，长期分支feat/p6。
状态in_progress；独立参考先行阶段完成，正式计分与A/B、自动验收继续运行。

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
