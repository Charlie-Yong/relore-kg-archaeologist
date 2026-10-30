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
