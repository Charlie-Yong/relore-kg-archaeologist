# relore 项目历史知识图谱

基于 relore 的开源项目历史知识图谱自动构建与可追溯问答，以 Flask 为主要实验对象。

**最终成品：输入仓库链接 → 自动采集 → 自动提取实体和关系 → 自动建立图谱 → 提问并获得答案和出处。** 一次配置凭据与已批准预算后，建图不要求用户选择案例、填写提交编号或人工补关系。

第一版支持公开GitHub Python仓库、每次一个仓库、程序自动限制采集范围；首次接入需等待处理，页面展示进度、实际覆盖与缺口。Flask完成主要课程实验，另一小型仓库仅验证换链接免改代码运行。不承诺任意语言、任意体量或全部历史。时间线仅保留简单表，依赖/比较复用已有数据，不为辅助展示扩大采集。

本仓库已按用户授权公开，规划可直接阅读；提交和管理仍按实际授权。密钥、私有测试参考和个人材料不在公开仓库中保存。

**当前交付（2026-10-30）：URL自动流水线、真实LLM抽取、Neo4j与同源检索、统一问答接口、Streamlit原型及正式实验汇总已接通。** 默认Flask URL作业已完成全部六阶段并发布ready，冻结369来源、40个完整讨论单元和24个源码快照，产出133个业务实体、183条关系、333份证据，其中61个Decision已包含在实体总数中。P3只读增量分片另生成18 Developer、384 Function、20 Authored、4 Merged、384 Defines及508条证据，并核对PR #6096到`flask.testing._get_werkzeug_version`的固定链。40个生产抽取run共42次实际尝试，含重试；30个测试线程的抽取P/R/F1为0.568/0.962/0.714。24道题保存48个A/B答案并由24次匿名评审覆盖，测试事实覆盖A/B为0.600/0.740，配对差0.157但95%描述性bootstrap区间跨零。全池首轮6个失败位置经一次格式恢复重试后为92/92，6道候选均完成两遍核验；确认证据不足0，正确弃答率N/A仅因合格分母0。第二仓库`pallets/itsdangerous`以同一入口生成347来源、30完整讨论、17文件快照、82实体、78关系、180证据，依赖查询返回50路径、25证据、5 claims且出处/SHA校验通过；job因真实采集缺口保持partial。最终共享账本保守累计9.465795元，approved=20、effective cap=19.84，余10.374205元。姓名、学号、职责确认和互评按当前要求留空。

公共接口见[流水线与CLI](docs/public_interfaces.md)、[图与查询](docs/graph_query.md)、[模型与证据](docs/p4/models.md)；[公开冻结重建包](repro/README.md)可无网络回放来源并重建图和索引，不需要本组密钥。原型入口为`app/main.py`。期末汇报使用`demo/final/期末汇报_20261030最终版.pptx`，共10页；期中五页版只作历史阶段材料。[技术报告正文](reports/technical_report.md)为期末统稿，正式PDF见`output/pdf/historykg_technical_report.pdf`。逐项课程验收见[demo验收矩阵](evaluation/results/course_acceptance.json)。打包工具支持`--package-status final_candidate`；只有最终PPT存在且由待打包提交跟踪时才允许`final`，并继续排除私有测试、凭据、个人配置和完整clone。Windows真实验证及限制以[重建记录](repro/README.md)和对应CI结果为准，不把安装说明当作实测。

**已完成的前期工作归属P4：** 项目起初调研、总体方案起草、多轮架构迭代、现有全部规划与规划协作框架、独立原型和期初小规模真实试跑，均由P4独立负责完成，计入其累计贡献。详见[P4前期工作与贡献记录](deliveries/P4/2026-10-27/handoff.md)，后续报告分工与展示引用该记录。

本次优先修复试跑暴露的错误，明确API元数据证据与关闭声明/关闭事件的差别，再扩大自动采样和接通自由提问。架构理解至少用已采源码实际回答一题有限模块依赖或职责问题；保持原范围、六人职责、两项正式实验和课程日期。

1.3.1精简执行要求：API证据共用一份冻结JSON；详细交接只维护一处，STATUS/PR引用；日常改动做相关检查，阶段集成集中独立复核，正式实验完整执行。六份工作单仍保留完整公共契约。接下来按已有规划修复与集成，不新增功能或评审层级。

1.3.2修正Release身份为repo与原样tag，避免同提交的不同标签被合并；代码实验统一为12个单文件快照（4开发/8测试），前后比较复用已采快照。默认采样规则保持，按现有安排试跑校准。

## 完整系统：安装与运行

Windows PowerShell，在仓库根目录运行：

~~~powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force .local
Copy-Item config/project.example.json .local/project.json
~~~

在本机`.local/project.json`设置PostgreSQL地址及自己已批准的共享账本额度；通过环境变量配置GitHub只读访问、`DEEPSEEK_API_KEY`和`HISTORYKG_NEO4J_URI`。不复制本组密钥或账本路径。服务安装见[采集器说明](docs/collector.md)，原生Windows自动化步骤见`tools/ci/start_windows_services.ps1`。首次建图会访问GitHub和模型并产生相应账户费用。

~~~powershell
.venv\Scripts\python -m historykg.cli doctor
.venv\Scripts\python -m historykg.cli build https://github.com/pallets/flask
.venv\Scripts\python -m streamlit run app/main.py
~~~

页面可直接输入URL并观察同一持久作业，发布后输入自然语言问题。CLI的`build-status`只读状态，`resume`从未完成阶段继续；全部选项见`.venv\Scripts\python -m historykg.cli --help`。需要无新增模型费用地重建已交结果时，按[冻结重建说明](repro/README.md)操作，不重新build。

## 底层采集器：独立开发小样

基于开源relore二次开发，P4负责移植、适配、基础数据接口及维护。[完整安装/调用说明](docs/collector.md)包含Windows PowerShell、macOS、SQLite/PostgreSQL及P1/P2接口；原始来源和许可证见[第三方说明](THIRD_PARTY_NOTICES.md)。

macOS快速示例，在仓库根目录运行：

~~~sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m historykg.collector doctor
.venv/bin/python -m historykg.collector ingest https://github.com/pallets/flask
.venv/bin/python -m historykg.collector search 'Flask' --repo pallets/flask
~~~

默认开发小样最多一个PR和一个Issue，使用本地SQLite；PostgreSQL为正式主线。它不调用模型，不是完整系统的自动建图验收。源码、基础接口、验证及交接均计入P4的已完成贡献。

## 成员如何开工

首次把本人对应的一份完整工作单交给AI；AI已有仓库访问时，给该文件路径即可。**AI必须先只读理解，并在聊天中向成员讲清项目原理，再开始实施。** 讲解覆盖成品目标、自动获取新仓库资料、API与费用、数据三种用途、模型/图谱分工、开发测试隔离、六人协作与本人职责，结合具体例子和当前进度，不能只说“已理解”或发送文档链接。完整要求见[统一执行契约C0](01_统一执行契约.md#c0-开工前必须向成员讲清项目原理)。

本项目调用现成模型，不训练或微调基础模型。运行资料增加可查询范围，开发样本用于发现问题后修改程序，独立测试用于评价冻结后的效果。软件不依赖预装Flask数据；使用者配置自己的API Key及数据库后，为新仓库自动获取并保存资料，复用的是处理程序。课程另附冻结实验资料供复现。

讲解结束后，AI按已有授权检查环境、恢复/建立个人分支并开始首个可运行产物，不要求成员答题或回复“可以开始”；成员提问先解答。只收到通用规划且无法唯一确定角色时才询问分工。

后续恢复会话时，AI自行读取STATUS、最新交接、请求和现有成果，核对handoff中的讲解发送记录；无记录先补讲，有记录且目标/角色未变则简述现状继续。缺上游先登记请求并推进独立任务；常规提交、审核、技术确认、集成、报告和PPT都由角色AI完成。已有实现与正式质量验收分别依据实际运行记录。

| 角色 | 工作单 |
|---|---|
| P1 数据与集成 | [P1工作单](P1_数据与集成_给成员AI.md) |
| P2 图谱与查询 | [P2工作单](P2_图谱与查询_给成员AI.md) |
| P3 代码与演化 | [P3工作单](P3_代码与演化_给成员AI.md) |
| P4 开源移植、基础数据接口与模型抽取 | [P4工作单](P4_模型与知识抽取_给成员AI.md) |
| P5 原型与汇报 | [P5工作单](P5_原型与汇报_给成员AI.md) |
| P6 模型参考与实验 | [P6工作单](P6_模型参考与实验_给成员AI.md) |

P4使用macOS，其余Windows；P2使用现有DeepSeek可执行开发工具，其余五人Codex；全员已有DeepSeek API。除确需本人接管的环节外，全部项目工作交给AI。成员只处理本人登录/权限、缺少或超出已批预算的费用决定、必要设备动作、理解与现场表达和真实互评。代码、配置、数据核验、评分、交接、报告/PPT与打包均由AI执行；不安排逐条人工标注评分。

“自动开工”指AI在已经打开且具备相应工具权限的会话中，先完成上述讲解再执行；仓库文件不负责启动另一台电脑或唤醒已结束的会话。会话恢复后AI按记录自行续做，不要求成员重述方案。

成品的自动运行另由P1交付持久任务和单worker：P3自动补代码/提交/发布，P4自动抽取，P2自动建索引与图，P5显示任务并接通问答，P6检验全过程及质量。它不依赖六位成员的开发AI会话一直在线。

## 组长与维护入口

- [总规划与组长使用说明](00_总规划与组长使用说明.md)
- [统一执行契约](01_统一执行契约.md)
- [relore与Flask可行性记录](02_relore与Flask可行性记录.md)
- [范围与契约变更记录](03_范围与契约变更记录.md)
- [成员与仓库登记](coordination/成员与仓库登记.md)
- [当前修订与检查记录](deliveries/planning/2026-10-28-v1.4.1/README.md)
- [v1.4.0采集器与基础接口交付](deliveries/planning/2026-10-27-v1.4.0/README.md)
- [v1.3.2身份与样本单位修正](deliveries/planning/2026-10-27-v1.3.2/README.md)
- [v1.3.1执行要求精简](deliveries/planning/2026-10-27-v1.3.1/README.md)
- [v1.3.0试跑反馈修订](deliveries/planning/2026-10-27-v1.3.0/README.md)
- [v1.2.0自动建图目标修订](deliveries/planning/2026-10-26-v1.2.0/README.md)
- [v1.1.1降风险修订](deliveries/planning/2026-10-26-v1.1.1/README.md)
- [v1.1自动开工修订](deliveries/planning/2026-10-26-v1.1/README.md)
- [v1.0初始交付记录](deliveries/planning/2026-10-26/README.md)

期中：**2026年11月11日，每组5分钟**。内部完整候选：**12月20日**。实际期末提交日期以老师通知为准。

主要实验对象为[pallets/flask](https://github.com/pallets/flask)。项目历史采集器基于[huggingface/relore](https://github.com/huggingface/relore)二次开发，固定源码已纳入项目；本组实现项目化接入，并继续开发URL流水线、版本关系、LLM决策理由抽取、知识图谱、应用与实验。代码/Commit/Release由P3从目标官方来源补充。

## 检查规划资料

PR和main提交自动运行Planning checks，成员无需手动触发、打卡或填表。检查只用公开文档和合成回归，不调用付费模型。对应角色AI查看结果并修复，真实系统由接收方AI另行复跑验收。

以下命令也可由AI本地运行，文档绿灯不代表系统运行通过：

~~~text
python tools/sync_workorders.py
python tools/check_planning.py
python -m unittest discover -s tools -p "test_*.py"
~~~

Windows可使用py -3运行，macOS可使用python3。工具仅用Python标准库。检查接受六种合法进度状态，日期使用实际执行时的北京时间；--initial-snapshot仅用于额外核验初始全todo快照。六份工作单的公共段必须与统一契约一致，状态文件中的后续实现不得提前标完成。
