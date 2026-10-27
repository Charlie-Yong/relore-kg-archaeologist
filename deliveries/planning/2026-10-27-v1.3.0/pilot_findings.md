# 10月27日试跑事实与修订交接

2026-10-27｜对应规划v1.3.0 / 契约1.3.0。本文汇总已归档小样，不是本次维护新跑出的结果。正式接口以[统一执行契约](../../../01_统一执行契约.md)为准。

## 1. 结论与归档身份

技术链路已真实走通，知识质量未通过，原型最终job为partial。独立原型使用relore采集和PostgreSQL检索，新增git/代码、DeepSeek抽取、Neo4j与问答适配；不是此前手工拼接摘录的示例。不能据此标记正式六模块完成或课程实验通过。

- job_id：20261027-105134-8b5d92。
- dataset_id：dataset:8de7947241c999f090ed0d5931b96f1bcbe72e67f831ffc7517a3d32d116a644。
- repo：pallets/flask；原型contract_version=pilot_v1，profile=pilot_small_v1；不是course_small_v1默认规模。
- relore：0.3.19，固定源码06a1c99c4653e9db899a18e96d8ff0ee6b419815；PostgreSQL 16.4；Neo4j 5.26.0；模型实际返回deepseek-flash。
- 本地原档定位：试点机知识图谱工作区的`relore实际试跑/runs/20261027-105134-8b5d92/`；原型代码在`relore实际试跑/historykg/`。这只是现有产物定位，不是正式部署所需路径。其他成员没有该目录时先用本契约fixture实现，通过P1的产物交接取得所需代码/原文，不能宣称已复跑。

## 2. 实际数量与通过范围

| 项目 | 已归档结果 |
|---|---|
| 自动来源选择 | 从100个关闭PR候选中选2个PR：#6096、#6133；补采Issue #3193；3个Release；每PR最多2个Python文件的前后快照 |
| 冻结来源 | 40条；检索数据库有3个线程、16个relore文档及40条补充来源记录，后者是共同来源视图，不能与40条冻结来源相加 |
| 实体 | 20：Project 1、PR 2、Issue 1、Release 3、Commit 2、File 8、Decision 3；File是4条路径的前后状态 |
| 关系 | 20：原型Closes 1、HasRelease 3、MergedAs 2、Touches 4、ChangesTo 4、ABOUT 3、EVIDENCED_BY 3；原型Closes未按1.3.0关闭事件标准验收 |
| 证据与结构 | 17条证据；哈希、引文偏移、端点、数据集、答案引用和路径校验通过；错误偏移和缺端点被拒收 |
| 重复导入 | 两次均20个实体、20条关系，没有重复增长 |
| 模型用量 | 6次真实请求，总12492 token：输入7670、输出4822，包含一次2000 token截断；恢复轮次的new_model_requests不是累计总数 |
| 问答 | 同一固定问题执行A/B；A返回3条claims，B返回4条；未验证自由提问界面，也未形成正式多题比较 |
| 模型评审 | judge评10项，8 supported、2 unclear；已发现漏判，不能称80%准确率 |

模型6次为：抽取成功1次、另一抽取截断1次及关闭thinking后的重试1次、A/B回答各1次、judge 1次。受本次调用上限限制，没有执行独立完整reference，因此没有抽取Precision/Recall/F1。正式网关不能因这次小样省略reference，也不能把6次/2000输出token设为未经验证的默认。

选定提交不在3.1.3、3.1.2、3.1.1标签的祖先集合中，没有生成ReachableIn或声称首次发布。没有Imports边，只有静态解析材料；“能列修改文件”尚不等于完成架构理解问答。

## 3. 已知缺陷与开发回归

以下入口来自已冻结试跑材料，链接供定位；远端内容后续变化不替代原档。它们现在全部属于开发主题，不能再放入正式盲测。

| 开发案例 | 观察到的问题 | 修订后的预期与责任 |
|---|---|---|
| [Flask PR #6133](https://github.com/pallets/flask/pull/6133)引用[Werkzeug PR #3219](https://github.com/pallets/werkzeug/pull/3219) | Werkzeug新增client.query被挂成Flask PR的新增决策；judge未识别 | P1提供repo目录，P4保留external_project候选及出处，不产本地Decision；P6用归属上下文检验评审 |
| 同一Flask PR的测试调整 | 原文明示因Werkzeug尚未发布而调整，rationale却为null/not_stated | P4抽取本地调整及明示理由；P6将空理由计漏抽，不因statement已含原因而判理由字段成功 |
| [Flask PR #6096](https://github.com/pallets/flask/pull/6096)指向[Issue #6093](https://github.com/pallets/flask/issues/6093) | 完整URL未补采；回答把Fixes声明直接写成修复事实 | P1解析URL并补采或记缺口；P2分声明/关闭事件；P4措辞与证据一致；P6检验夸大 |
| PR #6133的关闭声明指向[Issue #3193](https://github.com/pallets/flask/issues/3193) | 原文确实含该声明，但仅有声明不能证明关闭或行为修复 | 不擅自替换原始编号，也不沿用原型Closes为已验事实；P1查关闭事件，P2按1.3.0导入 |
| API元数据与模型请求 | 原型api_response未列入旧契约；一次HTTP成功却因思考占满输出上限截断 | P1/P3冻结可复算JSON证据；P4记录实际模式、finish_reason、新run_id和全部用量 |

修正只作用于后续代码/新数据版本，原始预测与审计保留，不能把旧结果改成成功再报告。已有引文正确及独立judge支持也未阻止这些错误，后续必须分别验证结构与语义。

## 4. 接收顺序与尚未完成项

1. P1核对原型代码、锁定依赖和冻结原档，分交所属角色；按1.3.0重建来源/subjects/关系，接入正式Build入口及阶段枚举。原型stage=complete不能直接当成C2.1合法stage，数据版本重新分配；不搬入完整环境、clone或私有评审缓存。
2. P1/P2/P4修复上述采集、关系与抽取错误；P6执行开发负例，检查评审也能识别错误。回放已存响应可用于程序回归，新抽取配置的效果须另留真实请求，不混称在线试验。
3. P3提供已采源码/同SHA依赖证据，P2/P4真实回答有限模块依赖或职责问题；P5接通公共URL/进度/自由提问页面，显示覆盖与缺口。然后扩大到正式默认profile并记录资源/预算。
4. P6在来源规则冻结后按主题隔离开发与测试，独立生成完整reference和问题，完成两项正式实验；第二小库及Windows/macOS分别验收。

未完成：course_small_v1规模、正式接口集成、交互式URL进度/自由提问、架构最低实答、完整reference及正式抽取指标、统计性A/B结论、第二仓库、Windows与正式复现包。原型具备恢复/重复导入记录不等于正式全部故障场景通过。六角色STATUS保持todo，接收后按实际运行更新。

## 5. 原始记录校验值

本次维护只读取下列原档并计算SHA-256，没有重新调用模型或改写试跑预测。共享仓库保存本摘要；源码和必要开发原文由P1接收，原始模型评审仍留试点私有目录。哈希用于接收方核对同一份记录，不代表本仓库已经包含原档。

| 原档文件 | SHA-256 |
|---|---|
| 验收审计.json | 6ddb308c5ec3c581f0cd34ab70a997b257ef8691b8fe0af93c19b08658c6cf35 |
| 验证报告.md | cbb035da2cbe67075d32ac48d99fce8fafc4a84c2fe562f308eae03fc40b6860 |
| sources.jsonl | 7fb379c131c2d9b5b9c140fb8e61e81019b0d2e51c1f5ea1030cdf06d86e710f |
| runtime_checks.json | 40b2872ef7438b01ef7e267b5e1b6ad2603ec89a751f190589eaae3e5b127776 |
| graph_checks.json | ec8f7f0430b00f044920aea71a898256fea796752642ae88001cd171c704015a |
