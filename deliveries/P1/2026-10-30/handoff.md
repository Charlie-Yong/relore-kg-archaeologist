# P1 数据、公共契约与 URL 流水线交接

角色P1，2026-10-30，规划/契约1.4.1，独立副本relore-agents/p1、长期分支feat/p1。
阶段状态final_candidate：期末统稿、正式实验结果和第二仓库验收已完成，仅余真实成员信息、最终PPTX入包及现场/服务复核等人工项。

## 原理说明与授权记录

本轮主代理已先向用户发送C0八项完整中文原理讲解，再启动六角色实施。P1随后向主代理
发送了本人输入、处理、输出和上下游职责说明；由主代理面向同一用户协调。此处记录
“讲解已发送”，不冒称用户确认理解。用户已授权常规技术操作自行核查，未另行要求开始确认。
本轮使用Stop That Shit change技能，按现有职责实现，不派子代理，不读取P6私有测试。

## 已交付实现与归属

- `e0f4ab2`：公共Pydantic记录、稳定ID、UTF-8/LF读写、原文证据定位。
- `83aba79`：toy_v1、数据集公共验证、URL有限发现及P4 capture→C5映射。
- `c9c54fb`：唯一持久pipeline/CLI、配置样例、接口说明、checkpoint与预算状态；
  后续本交接所在提交包含外库同号关闭者的真实缺陷修复及对应负例。
- 普通merge接收P3 `41d6020`代码及最终`2fb6d55`文档、P4 `b95e0da`及`c014e9f`采集选单/
  恢复/逐请求响应checkpoint。未squash/rebase或删除长期分支。

公共接口以[实际说明](../../../docs/public_interfaces.md)为准。start_build/get_build/resume_build
返回BuildJob dict；阶段顺序discover/collect/code/extract/validate/index_graph。模块缺失、预算不足
明确blocked；只有实际LLM抽取、图和同源检索均就绪才发布ready/partial。页面刷新复用活跃job，
重启显式resume；同job不换dataset或冻结选单。JSONL和阶段检查点原子落盘，恢复核对哈希。

P1新增贡献是公共数据契约实现、来源/主体汇合、声明/事件关系、有限发现及唯一构建编排。
P4前期独立调研、方案架构、规划、独立原型与固定relore移植/采集器的贡献保持归P4，
见[其前期记录](../../P4/2026-10-27/handoff.md)。源码/发布/版本与AST关系归P3；本轮P1为接收和集成。

## 实际真实 URL 运行

输入仅https://github.com/pallets/flask、默认course_small_v1，以及已配置只读GitHub访问/
隔离PostgreSQL。本次未手填线程号、SHA、文件或人工补边，不执行目标源码。

- job_id：`b61942bf06b742e48860d064dffe6df2`。
- dataset_id：`dataset:810db3718867788c5acb0fa437cdbf62bc0f99cd8e7435e9261471225f5cd00c`。
- 已完成discover/collect/code；当前blocked于extract，原因是P4正式抽取入口尚未合入本副本。
- 全局校验：369来源、40个complete讨论单元、72实体、60关系、197证据、65主体，errors=[]。
- 来源包括157份API JSON、62份git输出、24份code、3份release_note、4份commit_message，
  以及正文/普通评论/review/inline评论；范围仍为本次自动池，不能称全量Flask。
- P3结果：24文件×SHA快照全部AST解析，Imports25、Touches8、ChangesTo8、Commit4、Release3。
  ReachableIn0和MentionsPR0按实际缺口保留，不猜发布或首次版本。
- GitHub/API/git网络累计182次，含失败/重试与官方Issue timeline。本轮P1未发模型请求。
  全组新增费用只受P4唯一共享账本及10元授权上限控制，不在本副本另开10元。
- 运行中发现同文本API重复GET仅retrieved_at不同的来源冲突，已修为保留首次冻结时间，
  原capture保留每次读取；复用同job重映射后继续。恢复timeline保留Link响应头以缓存分页。
  运行期间P1代码处于工作区，随后形成上述提交；最终校验使用本交接对应实现。

摘要与哈希见[实跑验证](ingest_validation.json)。完整来源与job留本机，不将环境/clone/大数据
提交Git。主代理已独立读取并复跑这批数据，确认来源校验通过；这仅接收采集/代码阶段，
不代表未运行的抽取、图、问答或正式课程实验通过。

## 验证、缺陷与边界

实际macOS/Python3.11.15，PYTHONPATH显式前置本副本及本副本vendor/relore，未导入主仓库旧模块。
doctor/采集成功使用指定固定relore源码。Windows安装命令已提供，未做Windows实机验证。
Neo4j driver已在主venv统一安装neo4j==5.26.0，其实际依赖pytz==2026.6已锁入requirements。
P1未直接连接图库或调用模型，能力记录相应为null。
Streamlit已解析并锁定1.66.1（含完整传递依赖），主venv已安装且import通过。

最终相关程序检查：ruff check historykg tests通过；pytest tests -q在专用SQLite/PostgreSQL
测试环境中59 passed（含P3及P4测试）。P1公共边界含偏移、中文emoji、重复引文、坏JSONL、
缺端点、跨数据集、API合并对象绑定、关闭声明不能升级、同commit不同tag、外库同号PR拒收；
pipeline合成替身测试只验证状态/恢复/后端门槛，不冒称真实抽取或图验收。

已按主代理复现修复：validator坏record统一返回errors；Closes producer与validator共用完整
repo+PR编号匹配。GraphQL bare typename/number不足，须repository.nameWithOwner或URL；
外库同号不得关联本库。官方event.commit_id只在精确等于本库已确认merged PR的SHA时可用。
PR当前merged、Issue当前closed或Fixes文本单独均不足以建立关闭事实。
正常有限采样/外部Imports等coverage说明保留，不单凭gaps将ready降为partial；最终状态取实际
阶段partial。worker锁改用操作系统文件锁，空文件和持锁进程退出后均可恢复；macOS已实跑
空锁/互斥/子进程异常退出回归，Windows实现仍待实机核验。

toy_v1是明确合成fixture：12来源、11实体、14关系、12证据，包含accepted有理由、accepted无理由、
proposed三Decision和分页缺失。它不算真实知识抽取、正式实验样本或项目材料。

日常实现按C3.3运行上述受影响检查；主代理已独立复核公共接口并实跑来源消费者。
完整新流水线/模型/图库在阶段集成时仍需另一上下文实际复跑，尚不标verified_real/done。

## 恢复命令和接口

当前完整本机输入位于本副本：

~~~text
.local/jobs/b61942bf06b742e48860d064dffe6df2/job.json
.local/jobs/b61942bf06b742e48860d064dffe6df2/snapshot/snapshot.json
data/dataset-810db3718867788c5acb0fa437cdbf62bc0f99cd8e7435e9261471225f5cd00c/
.local/project.json
~~~

接入P4抽取、P2图谱模块后，在保留本机配置的P1副本调用（其他副本传同份config）：

~~~python
from historykg.io import read_json
from historykg.pipeline import resume_build
config = read_json(".local/project.json")
job = resume_build("b61942bf06b742e48860d064dffe6df2", config=config, background=False)
~~~

凭据从已授权配置读取到环境变量，不能打印/写入交接。P3 code-input/sources.jsonl已固定，
勿改为全局sources路径；真实job已完成code，正常resume不重跑已验阶段。

P2入口load_dataset(dataset_dir,config=...)返回dataset_id/graph_ready/retrieval_ready；
query返回公共QueryResult模型，CLI自动转dict。P1透传根database_url及graph配置、answer/model和
唯一共享budget。P5仅调用公共构建及P2查询，不能另建流水线。relore命中到C5的映射已写在
每份讨论来源的relore_mapping（repo/number/source_type/source_id），供P2共用。

后续责任：P4交真实抽取/统一回答，P2交Neo4j与共同来源检索，P5接公共界面和期中材料；
P1接着恢复同job、真实查询及集成验收。此次数据作为产品/开发验收；正式实验由P6独立控制，
不把现有调试抽取/问答直接计正式成绩，不接触private_test。主代理本轮明确暂缓
本40单元付费extract，先由P6冻结主题划分及独立参考/复核，明确放行后再从原job继续。
P4已交776e556、P2已交d972d08，正式集成由主代理协调，P1此时不重复调用。

原job元数据已按冻结文件只读重算：coverage含369来源、40完整单元、24代码快照、
时间范围、profile上限及缺口计数；counts保留全局口径，module_counts另存stage_counts。
未改冻结源和182已耗网络计数。resume允许显式传新服务端点/graph配置，保留原profile、
model和共享账本；数据库迁移不因此换来源输入。

## 可交 P5 的期中事实素材

本项目把公开仓库的讨论、提交、源码与发布材料统一保存为可复算来源，调用模型抽取决策和理由，
用显式图串起证据并回答自然语言问题。目前已完成公共契约和可恢复构建入口，首次默认Flask URL
自动采40个完整讨论单元并取得24份源码快照，369条统一来源的原文哈希、引文和端点校验通过。
现阶段抽取、图和问答仍待接通；期中只展示实际运行材料，之后验证完整闭环和独立对照实验。
P4承担前期方案及采集基础，P3承担版本源码，本轮P1承担数据与编排接入。

## 分支和PR送达

本批修复提交7dba6c5已实际推送feat/p1，已创建[PR #4](https://github.com/Charlie-Yong/relore-kg-archaeologist/pull/4)。推送与PR能力据实际结果更新，尚未做GitHub合并。主代理接收后按C3.3复跑受影响流程；本阶段不代表P1整体done。

P5调用P2时传pipeline.query_config(pipeline.load_config(...))，与CLI和pipeline load相同，统一展开服务配置、answer/model回退及唯一共享预算，不由页面另做映射。

## Windows、最新主线与候选包复核（2026-10-30）

PR #4当前提交e107439的三项远端检查均已成功。Windows run
41014535324（job 123927748027）在windows-2022上安装锁依赖并启动原生
PostgreSQL 16.4和Neo4j 5.26.0；上传JUnit共150 tests、0 failures、0 errors、
0 skipped。上传记录中toy_v1与Flask冻结包均首次加载ready，Flask重复加载幂等，
369来源、40完整单元、133实体、183关系、333证据，指纹
5cbe7b6f68a74d31ebf1fceeb7a00fd16d9b3737066b1ac7e9e51f90be955cfe，
新增模型请求0。PostgreSQL日志中的pgvector不可用仅说明部署采用既有词法回退，
没有把该可选扩展计入成功条件。脱敏摘要见[平台验证](platform_validation.json)，
原始JUnit、服务日志和两份重建JSON由Actions artifact
`windows-verification`保存，不提交到Git。

随后普通merge origin/main到feat/p1，接收P6正式抽取公共汇总，并在本机同一
PostgreSQL/Neo4j配置上运行全部150项测试，实际150 passed。新增
`test_old_published_job_display_is_correct_without_rewriting`确认旧ready job的展示用量
可从既有checkpoint只读恢复，既不触发阶段也不改写原job.json。技术报告已加入
P6测试集TP/FP/FN=25/19/1、P=0.5682、R=0.9615、F1=0.7143和理由覆盖13/15，
同时保留银标局限；报告PDF已重新生成并逐页渲染检查。复现目录附Flask BSD-3-Clause
许可证，新增候选成品打包工具拒绝私有测试目录并使用准确干净提交。

该记录描述当时的阶段放行状态；P6下游A/B、全池核验、第二仓库和完整课程材料的期末
结果已由本文件末尾“期末统稿最终验收”更新。原job仍保持ready，禁止重新resume、
采集或抽取。

## 期末统稿最终验收（2026-10-30）

独立工作树为`relore-agents/p1`，分支`feat/p1`。已普通合并主集成分支
`feat/p1-report-candidate`当前提交`2150aa6`，保留历史并形成合并提交`f0077ae`；
未reset/rebase，未在主共享目录执行checkout、commit或reset。本轮只修改：

- `reports/technical_report.md`
- `reports/build_pdf.py`
- `output/pdf/historykg_technical_report.pdf`
- `README.md`
- `00_总规划与组长使用说明.md`
- `coordination/STATUS_P1.md`
- `deliveries/P1/2026-10-30/handoff.md`

报告口径已经统一为最终事实：Flask全池首轮6个失败位置经一次格式恢复重试后6/6成功，
最终92/92；6道候选均完成两遍完整核验，确认证据不足0，正确弃答率N/A仅因合格分母0。
P3只读增量为18 Developer、384 Function、20 Authored、4 Merged、384 Defines及508条
证据；固定链核对至PR #6096（lkk7→davidism）→`05e9c6b`→`src/flask/testing.py`→
`flask.testing._get_werkzeug_version`，没有Developer→Commit。第二仓库
`pallets/itsdangerous`作业`ebfd8c8dae5e4bcf998a79fef35de981`形成347来源、30完整讨论、
17文件快照、82实体、78关系、180证据；validate/graph/retrieval ready，job因真实采集
缺口保持partial；依赖查询50路径、25证据、5 claims，出处、逐字引文和SHA校验通过。
共享账本未重置：approved=20、effective cap=19.84，保守累计9.465795，其中known
7.771385、unknown upper 1.694410，余10.374205。P5期末材料统一为
`demo/final/期末汇报_20261030最终版.pptx`，共10页；期中五页版只作历史材料。成员
姓名、学号、贡献确认与互评均保留“待本人填写/待本人补充”，没有虚构。

PDF使用指定Codex primary runtime的`python3 reports/build_pdf.py`重新生成。结果为
`output/pdf/historykg_technical_report.pdf`，13页、345655 bytes、PDF文本抽取19806字符、
其中汉字10621字；SHA-256为
`86ae7707157ce38e7062b7204bdb0f54952e391567950094945dfb4802752b4d`。九类指定旧
状态词的扫描计数均为0，覆盖过期全池分母、过期第二库缺口、过期核验状态、过期正式
PPT页数、过期发布状态及过期阶段名称。最终指标、P3固定链、
第二仓库/依赖查询、预算、10页期末PPT和人员待补标记的文本提取检查全部PASS。

PDF共7个URI annotation，对应6个唯一外部URL；逐一实际请求均返回HTTP 200。pdfplumber
检出5个表格，边界全部位于页面可打印区域，无裁切；第7、11、12、13页另行渲染目视复核，
抽取结果表、A/B表、六角色表、成员表、互评表及参考文献显示正常，成员信息表未跨页拆行。

实际检查命令与结果：

~~~text
指定runtime python3 reports/build_pdf.py
  成功生成13页PDF

指定runtime python3 tools/check_planning.py
  passed=true；68份Markdown、246个本地链接；P1-P6均为done；errors=[]

指定runtime python3 tools/test_check_planning.py
  7 tests passed

P4独立工作树.venv/bin/ruff check reports/build_pdf.py
  All checks passed!

git diff --check
  通过
~~~

指定runtime自身未安装ruff（`No module named ruff`），因此Ruff使用另一独立工作树
已有的可执行环境运行，未安装包、未调用模型。规划测试及Markdown本地链接检查均使用
指定runtime完成。

仍需人工或P5处理的最终项：P5最终PPTX原件当前尚未随本工作树提交，`demo/final/`
当前只有`材料说明.md`，最终打包前必须由P5补齐并确认被待打包提交跟踪；六名成员须
本人填写真实姓名、学号、职责确认和互评，不能用Git作者名或AI结果代填；最终PPT须在
Windows/PowerPoint原生环境复核并完成课堂彩排；最终审计时Neo4j live bolt/HTTP未保持
在线，打包前需复验服务可用性。本轮未读取`evaluation/private_test`，未调用付费模型，
未修改P2代码、P5 PPT或`tools/package_submission.py`。
