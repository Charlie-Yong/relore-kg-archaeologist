# relore 与 Flask 可行性记录

2026-10-26｜只读源码/官方资料核对；**没有安装或运行课程系统，没有进行DeepSeek请求、正式采集或实验。**

## 1. 判断和版本依据

结论：适合作为采集与检索底座，仍需本组完成URL自动编排、来源选择、真实LLM抽取、Release/Commit关联、图谱、原型与实验。硬件判断来自依赖与小范围设计，不是性能保证。先实跑一个URL自动闭环，再冻结profile、规模和费用。

GitHub API读取确认：relore main=06a1c99c4653e9db899a18e96d8ff0ee6b419815；Flask main=d086db856be187255b8ec61ef409357393020f32。前者是初始源码核对基准，后者只作变更记录来源快照，不作为所有历史案例的源码版本。P1/P3需分别解析候选tag的完整SHA。

- [relore固定源码入口](https://github.com/huggingface/relore/tree/06a1c99c4653e9db899a18e96d8ff0ee6b419815)
- [依赖与许可证声明](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/pyproject.toml)：Python≥3.10，Apache-2.0，客户端轻量，无ML栈；本组统一Python3.11。
- [Changelog](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/CHANGELOG.md)：0.3.17首次PyPI发行、0.3.18于2026-10-12记录；修复过Windows路径。附件“尚未发布PyPI”及部分operations旧说明已过时。
- [完整线程抓取源码](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/relore/github/fetch_thread.py)：普通评论、review主体、inline评论/回复分页读取，有unread缺失状态。
- [文档构建源码](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/relore/ingest/index_thread.py)：保存review关联、回复和代码锚点；能否取得具体远端内容仍取决于权限/API状态。
- [CLI说明](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/docs/cli.md)、[运行说明](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/docs/operations.md)、[Agent接入](https://github.com/huggingface/relore/blob/06a1c99c4653e9db899a18e96d8ff0ee6b419815/docs/agents.md)：提供CLI/HTTP、采集/检索/clone；最终命令以锁定版本的--help与实测为准。

## 2. 复用与缺口

| 能力 | 已有资料支持 | 本组任务与验证责任 |
|---|---|---|
| Issue/PR正文和完整讨论 | 有抓取、分页、原文与信号处理 | P1自动发现线程、完整性/来源ID/原文映射，真实试采集 |
| Postgres词法与精确信号检索 | 有，非embedding检索 | P1部署映射，P2查询适配；确认补充来源对基线可见 |
| why/grep/symbol等代码定位 | 有相关实现/入口，面向clone当前状态 | P3另读历史SHA；不把HEAD能力当历史快照分析 |
| rationale/precedent | rationale类检索与独立precedent服务不同；后者仍有stub | P2按实际功能暴露，不承诺完整先例服务；检索不是结构化Decision抽取 |
| Release/Commit/历史代码 | 不能由已有讨论索引直接得到完整关系 | P3从官方git/GitHub/发布说明按通用规则自动补原文与关系，P1汇合冻结 |
| LLM知识抽取与理由 | 不由词法检索自动完成 | P4真实DeepSeek抽取，原文定位，P6独立参考实验 |
| 显式图与证据链 | 上游不是本课程完整KG | P2建模/Neo4j/查询；P5显示路径与缺口 |
| 输入URL后无人建图 | 上述能力不等于已有完整自动入口 | P1唯一pipeline/profile/持久作业与恢复；P5接入；真实验收待实施 |
| Windows/macOS | 源码与发行记录支持可移植设计，未做本组实跑 | P1/P2 Windows，P4 macOS；配置clone根与服务地址 |
| 部署与资源 | 无本地模型栈；仍需Postgres、Neo4j和前端 | P1/P2集中服务/锁资源，小语料测内存磁盘和时延 |

relore sample的since按线程updated筛选、抓取选中线程整体，不能代表日期后所有历史，也不能直接代替按编号种子采集。P1可用很薄的内部采集适配，但内部函数属版本绑定接口，需实际检查错误与升级影响。只经HTTP无法保证所有采集适配，所以“不改核心”不等于“所有交互只经HTTP”。

clone根应配置RELORE_CLONE_ROOT为可写目录；默认服务路径不适合照抄Windows。普通客户端/HTTP与冻结导出适合其他成员，不要求全队完整部署。源码扫描或Windows修复记录不等于六台电脑已验收。

## 3. 两个开发回归入口

v1.2.0起这些固定案例仅作开发回归，不能代替只输入URL的成品验收；默认自动来源选择不保证命中它们，也不要求用户填写编号。

[Flask固定版本变更记录](https://github.com/pallets/flask/blob/d086db856be187255b8ec61ef409357393020f32/CHANGES.rst)记录了下面入口；当前仅为候选，不是数据集或实验结果。另经GitHub API确认：#4995是PR，#5774是Issue（不是PR）；2.2.3、2.3.0、3.1.1、3.1.2标签均存在且为annotated tag。P3必须将tag对象继续解引用到commit，不能将tag对象SHA当源码提交SHA。

| 候选 | 入口与起查范围 | 还必须查清 |
|---|---|---|
| A：before_first_request移除 | 2.3.0相关条目，PR #4995；先查2.2.3→2.3.0 | 正确路径/移除提交、此前弃用与原文理由、PR/Issue链、tag归属；没有理由不能补造 |
| B：stream_with_context异步修复 | 3.1.2相关条目，[Issue #5774](https://github.com/pallets/flask/issues/5774)；先查3.1.1→3.1.2 | 由Issue追实际修复PR、对应差异、父提交、合并方式、发布依据及原始讨论 |

P1/P3核验事实和来源，P4核验理由是否明确，P6独立参考。自动主实验池不足以覆盖课程所需理由/修复实例时，在11月15日前按来源情况调整通用profile并登记，不能手工补测试答案所需材料冒充自动采集。固定回归与正式池分开，不能先写答案再寻找支持。

## 4. 首轮验证和范围冻结

1. P1/P2锁定relore版本、配置数据库与可写clone目录；Windows最小启动，P4在Mac配合验证。
2. P1从URL按默认profile发现/采集；P3自动追PR对应提交、文件及发布；P1合成统一来源与subjects，记录哈希/完整性。
3. P4完成DeepSeek真实最小请求和结构化Decision，引文定位成功；P6运行独立参考/评分小样，记录费用。
4. P1编排真实各阶段；P2建立共同来源检索/图并返回证据链，P5展示任务状态/覆盖/出处；中断恢复、重复导入、空结果及故障分别检查。
5. P1/P6据真实用量与覆盖校准自动上限；11月15日前冻结profile/来源/问题，11月29日前冻结方法/参考；另一个小型Python仓库只做免改代码自动检查。

目前全部运行步骤待实施。首轮检查结果应写各角色STATUS和handoff，不在本记录预填通过。

## 4.1 自动化目标的可行性与边界（v1.2.0）

一次配置凭据和已批准预算后，公开GitHub Python仓库的URL→自动采集/提取关系/建图→问答在架构上可实现；不是relore开箱即用能力。当前仍无真实端到端、吞吐、费用或跨仓库运行结果，不能宣称已验证。具体默认选择/上限、BuildRequest/BuildJob和就绪判据统一见执行契约C2.1，不在此另维护一套参数。

- 原始数据来自目标官方GitHub、git历史及发布说明；P1取得Issue/PR/讨论，P3自动补代码/Commit/Release，P4抽取Decision，P2建图。独立GitHub Discussions、站外交流及第二语言不在第一版。
- [DeepSeek JSON输出说明](https://api-docs.deepseek.com/guides/json_mode/)支持结构化输出接口，不能保证提取事实正确，仍需逐字证据校验和独立质量实验。
- [GitHub访问额度说明](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)表明采集受访问额度限制；已有授权只读访问可复用，P1实现自动等待/限额和恢复。DeepSeek key不能代替GitHub数据采集和数据库配置。
- 新增工作主要在P1自动编排、P3通用代码定位及联调；用削减案例深挖/辅助图抵消部分增量，不能承诺零额外工时或固定失败率。第一版按范围自动处理，证据不足就说明缺口，不让成员人工补图。

## 5. 来源使用与再分发

relore为Apache-2.0，[Flask许可证](https://github.com/pallets/flask/blob/d086db856be187255b8ec61ef409357393020f32/LICENSE.txt)为BSD-3-Clause；源码复用保留适用版权/许可证/NOTICE。讨论文字不因仓库代码许可自动获得相同许可：课程包保留必要来源片段、作者/链接/日期和用途说明，不默认整批公开再发布。规划仓库按用户授权公开；密钥、私有测试参考、私聊和未经许可的材料仍不提交。不擅自改变上游署名或声称原创实现全部功能。
