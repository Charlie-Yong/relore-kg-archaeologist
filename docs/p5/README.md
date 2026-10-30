# 原型入口与演示

P5页面仅调用P1构建和P2查询；资料采集、任务编排、图查询及统一回答器均沿用所属模块。

## 启动

在仓库根目录按锁文件安装依赖。一次配置由安装者完成，普通使用只输入仓库URL。
`HISTORYKG_PROJECT_CONFIG`指向P1项目配置；凭据仍由P1/P4后端从本机环境读取。

macOS：

```text
export HISTORYKG_PROJECT_CONFIG=/实际位置/project.json
PYTHONPATH=vendor/relore:. .venv/bin/python -m streamlit run app/main.py --server.address 127.0.0.1
```

Windows PowerShell：

```powershell
$env:HISTORYKG_PROJECT_CONFIG = "C:\实际位置\project.json"
$env:PYTHONPATH = "vendor/relore;."
.venv\Scripts\python.exe -m streamlit run app/main.py --server.address 127.0.0.1
```

本轮实际平台为macOS；Windows命令待实机验证。

## 正常操作

1. 填写公开GitHub Python仓库链接，点“开始整理”。P1按默认profile自动推进。
2. 查看当前阶段、实际覆盖和缺口。任务身份保存在页面地址中；浏览器刷新只读取同一任务。
3. 构建暂停/失败时可显式“继续构建”，调用P1恢复接口。未就绪时没有问答入口。
4. 后端发布ready或partial数据后，输入自然语言问题。页面按顺序展示全部claims，证据链接可定位到对应原文组件。
5. 展开证据查看quote、Unicode位置、来源链接与冻结版本；展开关系链查看后端返回的真实关系、方法和原文。

empty、unsupported、error分别显示，不根据空数组改写后端状态。
同一问题响应保存在页面会话中，普通重绘不会重复调用模型。
查询方式的辅助选项只复用已有记录；缺少适用资料时显示unsupported。

## 同一真实任务与冻结重放

安装者可设置`HISTORYKG_DEMO_JOB_ID`，页面启动后只调用get_build观察已存任务，
不重新start。任务目录由同一P1配置决定，不能用其他副本的默认目录冒充原任务。

设置`HISTORYKG_REPLAY_FILE`可进入显式标识的冻结结果重放，文件结构为：

```json
{"mode":"real_public_query", "recorded_at":"原响应保存时间", "job":{}, "queries":[], "provenance":{}}
```

job为公共BuildJob，queries为同一dataset_id的公共QueryResult。
重放模式不显示在线输入框、不启动构建、不调用模型；不能把重放时间当在线性能。
正式备份仅在同一真实作业的公共查询完成后保存，不使用toy或旧独立dev数据拼成Flask URL验收。
本地归档工具`python -m app.replay --job-id JOB --query 原result.json --output 冻结包.json`
只读取已存作业/响应，保存原query/model运行ID、文件SHA-256及保存时间；拒收未就绪、跨版本和toy。
这些是演示安装者命令，普通用户仍只填写URL和自然语言问题。

## 本轮验证

`python -m pytest tests/test_app.py tests/test_app_replay.py -q`：21项通过。使用明确的合成后端响应，覆盖七种构建状态、
四种查询状态、所有claims顺序、空claims仍保留关系链、刷新/恢复及冻结重放无在线调用。
它是界面逻辑验证，不是实际LLM、Neo4j或真实仓库全流程验收。

真实只读接入：同一Flask任务现为ready/index_graph，覆盖369来源、40完整讨论、24文件快照；
graph_ready、retrieval_ready及actual_llm_extraction均为真。浏览器已核对
[完成态](screenshots/flask-ready-20261030.png)、[覆盖缺口](screenshots/flask-ready-coverage-20261030.png)
与[自然语言入口](screenshots/flask-ready-question-20261030.png)。保留原暂停截图作为真实阶段记录。

冻结公共响应另完成两项问题验收：源码职责问题返回6条claims与37条证据，
[claim列表](screenshots/flask-architecture-claims-20261030.png)与
[逐字源码](screenshots/flask-architecture-source-20261030.png)均已核对；
`dev-01` 保留原 `empty` 状态。重放包保存原运行ID、响应哈希和保存时间，页面关闭在线输入和模型调用。
最终期中材料为
`demo/midterm/期中汇报_20261111_20261030正式结果版.pptx`；第5页已写入P6正式抽取与
A/B结果，并明确bootstrap区间跨零和正确弃答率N/A。五页逐页渲染、PPTX结构完整性、
版式几何、字体、页数、标题及精确重导入检查均通过。完整机器可读记录见
[formal_results_validation.json](../../deliveries/P5/2026-10-30/formal_results_validation.json)。
具体版本、任务与待验收项统一记录于[P5 handoff](../../deliveries/P5/2026-10-30/handoff.md)。
