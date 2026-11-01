# 冻结公开数据重建

`flask_frozen.tar.gz` 保存原 URL 作业生成的公开 Flask 来源、已验图记录和 relore 无网络回放输入。
不是新采集、在线模型测试或正式实验参考。无密钥、个人配置、完整 clone 或 P6 私有材料。

- 原 job：`b61942bf06b742e48860d064dffe6df2`
- dataset：`dataset:810db3718867788c5acb0fa437cdbf62bc0f99cd8e7435e9261471225f5cd00c`
- 压缩包 SHA-256：`b361eda156abba3b8af715b0c62cd3263ae76a1903aa8e88dca771c98af512de`
- 包内 manifest 的来源和文件哈希保持原样；其历史 capture_path 只是出处记录，重建不访问该路径。
- 第三方文本保留作者、原 URL 和来源时间；Flask 为 BSD-3-Clause，提交
  `548994ea0c61465574cbfdd636a894a692f54b94` 的原许可证随包附于
  licenses/Flask-LICENSE.txt，relore 许可证见仓库 THIRD_PARTY_NOTICES.md。

Windows Actions 在 `windows-2022` 安装锁定依赖，从 EDB / Neo4j 官方分发站取得
PostgreSQL 16.4 和 Neo4j Community 5.26.0，记录下载哈希，监听 loopback，运行全部工程检查，
再分别重建 toy 和本包。每包导入两次并核验相同计数、图与检索就绪及实际查询上下文。
不配置 DeepSeek 密钥，不请求外部模型。CI 记录上传到对应 run 的 windows-verification artifact。
这只能证明该 Windows CI 环境中的安装、状态恢复、冻结重建与检索，不等于同学电脑实测或 Windows 在线采集/抽取。

已配置 PostgreSQL 和 Neo4j 的 PowerShell 中运行：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m tarfile -e repro/flask_frozen.tar.gz .local/frozen
$env:HISTORYKG_PLATFORM_DATABASE_URL = 'postgresql://USER@127.0.0.1:16432/historykg_windows'
$env:HISTORYKG_NEO4J_URI = 'bolt://127.0.0.1:17687'
.venv\Scripts\python tools/run_platform_rebuild.py --dataset .local/frozen/flask --out .local/windows-validation/flask.json --question 'stream context'
```

服务创建步骤见 `tools/ci/start_windows_services.ps1`；该脚本使用 CI 的 RUNNER_TEMP/GITHUB_WORKSPACE，
本机使用时先将其设置为当前项目内可写目录。真实模型请求响应及费用记录由最终课程包另行收录，
本最小公开重建包不含参考、评分或模型原始运行日志。

事后执行版本和方法输入在包内 `exports/reproduction_metadata.json`，含42次生产抽取attempt与对应共享账本核算0.657140元。它明确为发布后核对，不改原manifest/图指纹；原记录1.440966元保留为历史保守上界。

## Developer/Function 四跳扩展数据

`flask_extended.tar.gz` 补交已经通过真实验收的 P1+P3 合并数据集，包含原文、
实体、关系、证据和同源检索输入。它与上面的 1.4.1 生产包分别保留；正式抽取和 A/B
统计仍使用原生产数据。此包用于重建扩展图，不重新执行采集、AST 抽取或模型调用，
因此不需要原电脑的 snapshot、git cache 或临时目录。

- dataset：`p2_p3_real_014e28d89e1f`，契约 1.4.2。
- 370 来源、535 实体、591 关系、741 证据；包括 18 Developer、384 Function。
- 压缩包 SHA-256：`ca29b75815a884f52e57b5692f70ae183f5fd40818041f75e4c7c8ed8c74d132`。
- 原验收图指纹：`d0c1be456f70acdf354776e2fbee24ee5d6614e94437add2a3e90239a48539dd`。
- 原 manifest 及其 18 份 JSONL 原样保留；新附交付元数据说明本次归档范围。
  Flask 原许可证同时附于归档内 `licenses/Flask-LICENSE.txt`。

沿用上面已配置的 Python、PostgreSQL 与 Neo4j，在仓库根目录的 PowerShell 运行：

```powershell
.venv\Scripts\python -m tarfile -e repro/flask_extended.tar.gz .local/frozen
$env:P2_REAL_P3_DATASET_DIR = '.local/frozen/flask_extended'
$env:P2_TEST_DATABASE_URL = $env:HISTORYKG_PLATFORM_DATABASE_URL
$env:P2_TEST_NEO4J_URI = $env:HISTORYKG_NEO4J_URI
.venv\Scripts\python -m pytest -q tests/test_graph_query.py::test_real_p3_merged_shard_loads_and_returns_four_hop_path
.venv\Scripts\python tools/run_platform_rebuild.py --dataset .local/frozen/flask_extended --out .local/windows-validation/flask-extended.json --question 'PR #6096 testing.py'
```

第一条验证运行已有真实分片测试，检查作者与合并者两条四跳关系及证据；测试结束会
清理该测试数据集。最后一条再导入两次并保留可查询扩展图，检查计数一致与图、检索就绪。
应使用课程测试数据库，避免对正在演示的同名扩展数据集运行清理测试。
macOS/Linux 使用 `.venv/bin/python`，相同环境变量以 `export` 设置。
运行范围与结果见 `evaluation/results/extended_frozen_delivery.json`；Windows 指令尚待本机复核。
