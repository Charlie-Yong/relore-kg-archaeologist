# relore 与 Flask 可行性记录

2026-10-26｜只读源码/官方资料核对；**没有安装或运行课程系统，没有进行DeepSeek请求、正式采集或实验。**

## 1. 判断和版本依据

结论：适合作为采集与检索底座，仍需本组完成真实LLM抽取、Release/Commit演化关联、图谱、原型与实验。硬件判断来自依赖与小范围设计，不是性能保证。两个真实案例试跑后才冻结规模和费用。

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
| Issue/PR正文和完整讨论 | 有抓取、分页、原文与信号处理 | P1种子线程适配、完整性、来源ID/原文映射，真实试采集 |
| Postgres词法与精确信号检索 | 有，非embedding检索 | P1部署映射，P2查询适配；确认补充来源对基线可见 |
| why/grep/symbol等代码定位 | 有相关实现/入口，面向clone当前状态 | P3另读历史SHA；不把HEAD能力当历史快照分析 |
| rationale/precedent | rationale类检索与独立precedent服务不同；后者仍有stub | P2按实际功能暴露，不承诺完整先例服务；检索不是结构化Decision抽取 |
| Release/Commit完整历史图 | 不能由已有讨论索引直接得到 | P3定向获取tag/commit/文件与关系，P1统一冻结 |
| LLM知识抽取与理由 | 不由词法检索自动完成 | P4真实DeepSeek抽取，原文定位，P6独立参考实验 |
| 显式图与证据链 | 上游不是本课程完整KG | P2建模/Neo4j/查询；P5显示路径与缺口 |
| Windows/macOS | 源码与发行记录支持可移植设计，未做本组实跑 | P1/P2 Windows，P4 macOS；配置clone根与服务地址 |
| 部署与资源 | 无本地模型栈；仍需Postgres、Neo4j和前端 | P1/P2集中服务/锁资源，小语料测内存磁盘和时延 |

relore sample的since按线程updated筛选、抓取选中线程整体，不能代表日期后所有历史，也不能直接代替按编号种子采集。P1可用很薄的内部采集适配，但内部函数属版本绑定接口，需实际检查错误与升级影响。只经HTTP无法保证所有采集适配，所以“不改核心”不等于“所有交互只经HTTP”。

clone根应配置RELORE_CLONE_ROOT为可写目录；默认服务路径不适合照抄Windows。普通客户端/HTTP与冻结导出适合其他成员，不要求全队完整部署。源码扫描或Windows修复记录不等于六台电脑已验收。

## 3. 两个候选入口

[Flask固定版本变更记录](https://github.com/pallets/flask/blob/d086db856be187255b8ec61ef409357393020f32/CHANGES.rst)记录了下面入口；当前仅为候选，不是数据集或实验结果。另经GitHub API确认：#4995是PR，#5774是Issue（不是PR）；2.2.3、2.3.0、3.1.1、3.1.2标签均存在且为annotated tag。P3必须将tag对象继续解引用到commit，不能将tag对象SHA当源码提交SHA。

| 候选 | 入口与起查范围 | 还必须查清 |
|---|---|---|
| A：before_first_request移除 | 2.3.0相关条目，PR #4995；先查2.2.3→2.3.0 | 正确路径/移除提交、此前弃用与原文理由、PR/Issue链、tag归属；没有理由不能补造 |
| B：stream_with_context异步修复 | 3.1.2相关条目，[Issue #5774](https://github.com/pallets/flask/issues/5774)；先查3.1.1→3.1.2 | 由Issue追实际修复PR、对应差异、父提交、合并方式、发布依据及原始讨论 |

P1/P3核验事实和完整来源，P4核验理由是否明确，P6独立建立参考。候选缺理由或关系无法确认时，在11月15日前换有证据主题并留记录；不先写答案再寻找支持。至少一条跨来源多跳链和一个真实Bug修复案例可复用同一案例，但理由抽取仍需有真实资料。

## 4. 首轮验证和范围冻结

1. P1/P2锁定relore版本、配置数据库与可写clone目录；Windows最小启动，P4在Mac配合验证。
2. P1采集两个候选完整线程；P3补相关tag/源码/commit，统一来源哈希和完整性。
3. P4完成DeepSeek真实最小请求和结构化Decision，引文定位成功；P6运行独立参考/评分小样，记录费用。
4. P2导入并返回证据链，P5展示真实原文与gaps；重复导入、空结果和断库分别验证。
5. P1/P6据数据量、API耗时、来源完整性、模型费用和错误校准规模；11月15日前冻结主题/来源/问题，11月29日前冻结方法/参考。

目前全部运行步骤待实施。首轮检查结果应写各角色STATUS和handoff，不在本记录预填通过。

## 5. 来源使用与再分发

relore为Apache-2.0，[Flask许可证](https://github.com/pallets/flask/blob/d086db856be187255b8ec61ef409357393020f32/LICENSE.txt)为BSD-3-Clause；源码复用保留适用版权/许可证/NOTICE。讨论文字不因仓库代码许可自动获得相同许可：课程包保留必要来源片段、作者/链接/日期和用途说明，不默认整批公开再发布。规划仓库保持私有，不擅自改变上游署名或声称原创实现全部功能。
