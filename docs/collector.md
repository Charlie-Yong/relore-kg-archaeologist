# 项目历史采集器｜安装、调用与交接

项目内模块，由P4负责源码移植、适配、基础数据接口及维护；基于开源relore二次开发。
固定版本为0.3.19 / `06a1c99c4653e9db899a18e96d8ff0ee6b419815`，源码在
[vendor/relore](../vendor/relore)，许可和来源见[第三方说明](../THIRD_PARTY_NOTICES.md)。
上游原始文档描述其自己的部署；本项目以本页命令为准。

## 1. 安装仓库内版本

以下命令都从本仓库根目录运行，要求Python 3.11和Git。下载第三方Python依赖需要网络。
运行时使用本机数据库，不连接relore原项目的默认服务。无需Neo4j或模型API。

Windows PowerShell：

~~~powershell
git clone https://github.com/Charlie-Yong/relore-kg-archaeologist.git
cd relore-kg-archaeologist
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m historykg.collector doctor
~~~

macOS：

~~~sh
git clone https://github.com/Charlie-Yong/relore-kg-archaeologist.git
cd relore-kg-archaeologist
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m historykg.collector doctor
~~~

`doctor`应返回`source.bundled=true`、`version=0.3.19`，源码路径指向本仓库的
`vendor/relore/relore/__init__.py`。未初始化时`schema_ready=false`，首次`ingest`会建表。
安装文件精确锁定第三方依赖，并将relore指向本仓库的可编辑源码；其版本和原始来源另行保留。

## 2. SQLite轻量开发示例

未设置`RELORE_DATABASE_URL`时，自动使用`.local/collector/index.sqlite3`。
若已设置数据库变量，可在PowerShell执行`Remove-Item Env:RELORE_DATABASE_URL`，
在macOS执行`unset RELORE_DATABASE_URL`恢复此默认值。

Windows PowerShell：

~~~powershell
.\.venv\Scripts\python.exe -m historykg.collector ingest https://github.com/pallets/flask
.\.venv\Scripts\python.exe -m historykg.collector search "Flask" --repo pallets/flask
~~~

macOS：

~~~sh
.venv/bin/python -m historykg.collector ingest https://github.com/pallets/flask
.venv/bin/python -m historykg.collector search "Flask" --repo pallets/flask
~~~

默认`collector_smoke_v1`从最近更新的候选中最多选一个PR和一个Issue，各类候选最多100条，
每次最多60次GitHub请求。Issue候选过滤PR，线程正文、普通评论、review与inline回复复用
relore的实际分页抓取；某类不存在、未读完或请求失败按实际结果记录。它是开发小样配置，
不是正式`course_small_v1`的40讨论单元流程。

可选参数为`--max-issues`、`--max-prs`、`--max-requests`、`--out`。讨论总量范围1–40，
请求上限1–300；上限覆盖分页、失败尝试和重试。一次请求最多重试2次，要求等待超过10秒时
保存阻塞状态，由调用方稍后重新执行。重复导入相同内容不增加文档数。

查询使用两个或三个有辨识度的关键词。以上示例可能查无结果；从实际采集的标题中选词
可核对已入库来源。空结果返回`empty`，不表示全仓库没有相关事实。

## 3. PostgreSQL正式主线

提供[本地Compose配置](../compose.collector.yml)，固定PostgreSQL 16.4，监听本机16432端口。
若已安装原生PostgreSQL，可直接使用已有服务上的专用数据库，不要求安装Docker。

~~~text
docker compose -f compose.collector.yml up -d --wait
~~~

PowerShell设置：

~~~powershell
$env:RELORE_DATABASE_URL="postgresql://collector:collector_dev@127.0.0.1:16432/historykg_collector"
.\.venv\Scripts\python.exe -m historykg.collector ingest https://github.com/pallets/flask
.\.venv\Scripts\python.exe -m historykg.collector search "Flask" --repo pallets/flask
~~~

macOS设置：

~~~sh
export RELORE_DATABASE_URL='postgresql://collector:collector_dev@127.0.0.1:16432/historykg_collector'
.venv/bin/python -m historykg.collector ingest https://github.com/pallets/flask
.venv/bin/python -m historykg.collector search 'Flask' --repo pallets/flask
~~~

`collector_dev`是Compose本地开发默认密码，可通过`COLLECTOR_POSTGRES_PASSWORD`调整。
原生安装使用同样的数据库URL形式，账户须可在专用库建表及创建`pg_trgm`扩展。
连接样例在[环境变量示例](../config/collector.env.example)；程序读取环境变量，不自动加载该文件。

公开仓库的小样允许匿名访问。若配置GitHub令牌，使用`GITHUB_TOKEN`，或已有`GH_TOKEN`；
仅需实际读取目标公开仓库的权限。令牌不写进命令参数、输出或Git。
网络代理沿用HTTPX支持的环境变量，安装依赖已包括SOCKS支持。

## 4. P1/P2可调用的数据接口

入口为[historykg.collector](../historykg/collector.py)，所有返回均为字典，
`interface_version=collector_v1`。这些是P4维护的基础数据接口；C2/C7的正式
`BuildJob_v1`、`QueryResult_v1`及统一来源ID由原所属角色在其上接入。

| 接口 | 输入 | 主要结果与职责 |
|---|---|---|
| `initialize_database(database_url=None)` | 可选连接串，缺省读取环境配置 | 幂等迁移、后端名称、线程和文档计数 |
| `doctor(database_url=None)` | 同上 | 实际源码位置/版本、是否仓库内版本、数据库可用性和建表状态 |
| `collect_repo(repo_url, *, database_url=None, max_issues=1, max_prs=1, max_requests=60, output_dir=None, token=None, transport=None)` | 公开GitHub Python仓库URL；可注入HTTPX transport用于冻结测试 | 自动发现、抓取、入库，返回选择清单、实际计数、请求量、覆盖缺口及capture路径；供P1调用 |
| `index_threads(payloads, *, database_url=None)` | 同仓库的relore `ThreadPayload`列表 | 将同一冻结原文写入目标索引，返回写入量和实际计数；支持复算和后端验证 |
| `replay_capture(path, *, database_url=None)` | 本模块生成的capture文件 | 无网络回放，保留原采集状态及缺口；不把回放称为新采集 |
| `search_history(repo, query, *, database_url=None, limit=5)` | 明确仓库、关键词；limit为1–10 | 复用relore排序，返回hits及扩展说明；供P2接入共同检索基线 |

Python示例：

~~~python
from historykg.collector import collect_repo, search_history

result = collect_repo("https://github.com/pallets/flask")
print(result["status"], result.get("capture_path"))
hits = search_history("pallets/flask", "Flask")
print(hits["status"], hits.get("hits", []))
~~~

采集结果包含`status,repo,profile_version,selected,indexed_threads,counts,gaps,
github_requests,max_requests,authenticated,capture_path`。`counts`是该库内指定仓库的当前计数，
`indexed_threads`是本轮实际处理数。capture保存来源时间、源码提交、实际HTTP响应、
`ThreadPayload`及运行结果，格式为`historykg.collector.capture.v1`。
capture是开发接口的冻结输入，不冒充正式C5统一来源包；P1后续负责映射及冻结。
`replay_capture`读取损坏、非本模块格式或跨仓库混用的文件时抛出ValueError/OSError，
调用方应将其作为输入故障处理；有效文件的数据库故障通过结果status报告。

检索hit包含`repo,number,thread_type,title,source_type,source_id,url,author,trust,snippet`
等relore字段。`source_id`是relore来源标识，不是C5的SHA-256 SourceDocument ID。
原文片段和链接用于核对，检索不生成模型答案或新的修复结论。

| 状态 | 含义 | CLI退出码 |
|---|---|---|
| `ok` | 本轮选中部分完成，或查询有命中 | 0 |
| `empty` | 成功执行但候选或命中为空 | 0 |
| `partial` | 已入库的可用前缀存在，同时有未读/失败/超限；必须展示gaps | 3 |
| `blocked` | 尚无本轮可用产物，受到请求预算或外部限流阻塞 | 3 |
| `unsupported` | 输入或仓库不在本入口支持范围 | 2 |
| `error` | 网络、存储或运行错误，不包装成空结果 | 2 |

## 5. 验证与恢复

基础测试使用合成讨论，不联网：

~~~text
python -m pytest tests -q
~~~

PostgreSQL测试必须使用独立、库名以`_test`结尾的测试库。测试会清理该库中的relore表，
不使用业务库或旧试跑库。Compose用户可先创建：

~~~text
docker compose -f compose.collector.yml exec postgres createdb -U collector historykg_collector_test
~~~

将`RELORE_TEST_POSTGRES_URL`设为该测试库连接串，再运行上述测试；未配置时PostgreSQL部分
明确显示skip。原包相关测试可从`vendor/relore`运行`python -m pytest tests -q`。

真实小样验证工具为`tools/run_collector_smoke.py`：

~~~text
python tools/run_collector_smoke.py --postgres-url postgresql://collector:collector_dev@127.0.0.1:16432/historykg_collector_test
~~~

该工具真实抓取一次Flask，再将同一capture回放到SQLite和给定PostgreSQL库，验证检索及
重复导入；报告保存在`.local/collector/validation/report.json`。它不调用模型。

常见问题：`bundled=false`时重新从根目录安装；断库时检查服务和连接串；限流或预算停止时
查看capture内的gaps，额度恢复后重跑；未建表时运行`ingest`或调用`initialize_database`。
`search`不自动建库，断库/缺表返回error。SQLite用于开发，正式实验继续使用PostgreSQL。

当前实测平台是macOS；Windows命令已提供，Windows实机流程按既定里程碑由相应成员补验。
