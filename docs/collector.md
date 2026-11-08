# 项目历史采集器

采集器负责从公开 GitHub Python 仓库取得有限范围的原文和出处。成品使用同一条流程：

**仓库链接 → 自动选取讨论 → 分页采集并冻结原文 → 抽取实体和关系 → 建图 → 有出处的问答。**

[发现模块](../historykg/ingest/discovery.py)选取候选讨论，[GitHub 读取模块](../historykg/ingest/github.py)
读取 Issue、PR 正文、评论、评审和行内评论，按 [GitHub REST 分页规则](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)
读取后续页面。采集入口保存 HTTP 响应和已用请求数，记录未读部分，并把统一的讨论记录交给
[来源映射](../historykg/ingest/capture.py)。文件、提交和发布仍由代码与版本模块补充。
[讨论索引](../historykg/ingest/index.py)以仓库、线程和来源编号保存记录，按标题和正文关键词排序，返回原文和链接。
冻结后，问答只使用当前数据集的来源。早期原型来源和许可证见[第三方说明](../THIRD_PARTY_NOTICES.md)。

## 安装与试采

在仓库根目录使用 Python 3.11 安装锁定依赖。Windows PowerShell：

~~~powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m historykg.collector doctor
.venv\Scripts\python -m historykg.collector ingest https://github.com/pallets/flask
.venv\Scripts\python -m historykg.collector search "Flask" --repo pallets/flask
~~~

macOS 或 Linux：

~~~sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m historykg.collector doctor
.venv/bin/python -m historykg.collector ingest https://github.com/pallets/flask
.venv/bin/python -m historykg.collector search 'Flask' --repo pallets/flask
~~~

`doctor`显示`source.implementation=historykg`、数据库类型和索引状态。`ingest`会自动建表；
默认 SQLite 路径为`.local/collector/index.sqlite3`。测试采集默认最多一个 PR、一个 Issue，
各看最近更新的 100 条候选，预算 60 次 GitHub 请求。正式构建仍用`course_small_v1`，
由流水线按采集计划交给采集器，最多 40 个讨论和 300 次 GitHub 请求。分页和重试都计入上限。

匿名访问适合小样；正式构建可用`GITHUB_TOKEN`或`GH_TOKEN`配置 GitHub 只读凭据。
设置`HISTORYKG_DATABASE_URL`可使用 PostgreSQL，例如
`postgresql://collector:collector_dev@127.0.0.1:16432/historykg_collector`。
本机服务可用`docker compose -f compose.collector.yml up -d --wait`启动，也支持已装的 PostgreSQL。
账户需能在专用库建表，正式冻结索引还需能建 schema。环境变量示例见[配置样例](../config/collector.env.example)。

## 数据接口

[historykg.collector](../historykg/collector.py)保持`collector_v1`接口。返回值为字典。

| 接口 | 作用 |
|---|---|
| `initialize_database(database_url=None)`、`doctor(database_url=None)` | 初始化或检查索引。 |
| `collect_repo(repo_url, **options)` | 发现并采集讨论，返回覆盖、缺口、实际请求数和`capture_path`。 |
| `index_threads(payloads, *, database_url=None)` | 从同一仓库的`ThreadPayload`写入索引；同一内容重复导入不增加文档。 |
| `replay_capture(path, *, database_url=None)` | 无网络回放，保留原采集状态与缺口。 |
| `search_history(repo, query, *, database_url=None, limit=5)` | 从指定仓库返回命中及来源 URL；`limit`为 1–10。 |

`collect_repo`接受`selected`作为发现阶段冻结的讨论清单，并通过`initial_requests`、
`initial_http_responses`接续同一预算。`resume_capture`沿用同仓库、同清单和已用额度；
已完成线程、带分页信息的成功响应直接重用。每次请求前保存次数、收到响应后保存原文，
因此中断时已发出的请求仍计数。`capture.json`保留`historykg.collector.capture.v1`结构，
新采集附`collector_version`。原始响应存于`http_responses`，不包含认证请求头。

| 状态 | 含义 | CLI 退出码 |
|---|---|---|
| `ok`、`empty` | 完成，或没有候选/命中 | 0 |
| `partial`、`blocked` | 有缺口的可用结果，或额度/限流阻塞 | 3 |
| `unsupported`、`error` | 不在支持范围，或请求/存储失败 | 2 |

## 已有数据和验证

现有采集快照可用`replay_capture`导入新索引；已建图的数据集使用
`python -m historykg.cli load <dataset_dir>`重新导入讨论索引。两者都从保存的数据读取。
旧的数据库连接环境变量继续兼容，优先使用`HISTORYKG_DATABASE_URL`。
[公开冻结包](../repro/README.md)可在无网络和模型密钥时重建。旧版实验及答案保持各自的原版本，
当前检索方法的新运行不能沿用旧实验分数。

`python -m pytest tests -q`验证分页、续采、回放、覆盖和同源查询。PostgreSQL 测试使用
`HISTORYKG_TEST_POSTGRES_URL`指向的专用`_test`库。需要在线验证采集时，可运行
`python tools/run_collector_smoke.py --postgres-url <测试库URL>`，用同一份真实采集结果核对
SQLite 和 PostgreSQL 中的检索、回放及重复写入。
