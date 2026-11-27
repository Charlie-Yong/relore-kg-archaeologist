# 公共数据和构建接口

P1维护，契约1.4.1。输入是公开GitHub Python仓库URL，正常建图不填线程号、SHA或路径。
项目历史采集与基础讨论检索归P4，代码版本事实归P3，Decision归P4，图/检索归P2。

## 公共记录

`historykg.contracts`导出SourceDocument、SourceUnit、Evidence、Entity、Relation、Subject、
BuildRequest、BuildJob、QueryRequest、QueryResult，并有除Subject外的`*_v1`别名。
模型字段对应统一契约C2/C5–C7；`model_validate`用于单记录，跨文件检查用`validate_dataset`。

`historykg.ids.stable_id(kind, repo, *keys)`为规范repo和紧凑UTF-8 JSON数组的完整SHA-256。
Project无额外键；Issue/PullRequest键为整数编号；Commit为完整SHA；Release为原样tag；
File依次为完整SHA、仓库相对path。`relation_id(repo,type,from_id,to_id)`标识有向关系。
Decision用`decision_id(repo,unit_id,subject_id,action,status,statement)`，statement折叠空白。

`historykg.io`提供：

- `make_source(*,dataset_id,repo,kind,url,text,origin_key,retrieved_at,occurred_at=None,author=None,trust_tier='unknown',api_metadata=None,**extra)`：仅转LF，生成哈希和source_id，返回dict。
- `freeze_api_source(*,dataset_id,repo,endpoint,payload,retrieved_at,params=None,response_status=200,origin_key=None)`：完整JSON规范表示，格式在manifest注明。
- `locate_evidence(source,quote,*,start=None,before=None,after=None)`返回`(start,end)`；`make_evidence`同签名，返回Evidence dict。重复quote须明确偏移或上下文，不任取首项。
- `read_jsonl(path,model=None)`与`write_jsonl(path,records)`；`read_json`、`write_json`；输出UTF-8/LF并原子替换。
- `merge_sources(dataset_dir)`汇合全局及p1/p3/p4源分片，不改原分片；`build_subjects`生成主体目录。
- `validate_dataset(dataset_dir,check_manifest=True)`返回`status,dataset_id,counts,errors`，拒收坏哈希、引文、端点、跨数据集与API关系上下文等。

Evidence偏移是Python Unicode码点、0-based、左闭右开。API合并/关闭边必须保留完整对象，
绑定实际PR/Issue编号及SHA；Fixes声明只支持ClaimsToClose。

## 唯一构建入口

`historykg.pipeline.start_build(request, *, config=None, background=True)`、
`get_build(job_id, *, config=None)`、`resume_build(job_id, *, config=None, background=True)`
均返回BuildJob dict。request接收BuildRequest或`{'repo_url':URL,'profile':'course_small_v1'}`。
页面轮询get；start对同URL+配置已有queued/running/blocked任务复用job_id，blocked需resume。
同一进程单线程worker，跨进程worker锁，job/request/config/阶段checkpoint持久保存在`.local/jobs`。
进程结束后显式resume续作，不承诺应用关闭时仍后台运行。

默认配置读`HISTORYKG_PROJECT_CONFIG`或`.local/project.json`。凭据仅环境变量，
配置内API key/token会被拒绝。首次配置使用[示例](../config/project.example.json)；
预算示例为0，须填写已有授权的共享账本和上限。开发期本轮共享账本不得各角色另开。
数据库密码若使用连接串属于本机配置，不提交真实配置。

阶段调用依次为：P1 discover/collect →
`historykg.code.run_code_stage(snapshot_dir,*,dataset_dir,profile,budget)` →
`historykg.extract.run_extract_stage(dataset_dir,*,config,budget)` → P1 validate →
`historykg.graph.load_dataset(dataset_dir)`。最后需返回当前dataset_id及
`graph_ready=true,retrieval_ready=true`，且extract确有`usage.actual_llm_extraction=true`。
模块缺失/模型预算缺失返回blocked；未形成可查询图与共同检索不能标partial/ready。

P3读取snapshot_dir/snapshot.json：repo、dataset_id、profile、selected、完整官方selected_prs、
repo_metadata、可空default_branch_sha、sources与paths.sources。paths.sources指向collect后固定的
code-input快照，不能指随后扩充的全局sources。P3写p3分片，P1统一合并后才调用抽取。

## 命令与错误码

安装见[采集器说明](collector.md)。以下均在仓库根目录，Windows使用
`.venv\Scripts\python.exe`，macOS使用`.venv/bin/python`替代python。

~~~text
python -m historykg.cli --help
python -m historykg.cli doctor
python -m historykg.cli fixture --out fixtures/toy_v1
python -m historykg.cli --config .local/project.json build https://github.com/pallets/flask
python -m historykg.cli build-status JOB_ID
python -m historykg.cli resume JOB_ID
python -m historykg.cli validate DATASET_DIR
python -m historykg.cli query "问题正文" --dataset-id DATASET_ID
~~~

开发复现另有ingest（冻结capture→C5）、code/extract（同job推进到指定阶段）、load、export、
evaluate（P6提供）。这些不是正常用户必走步骤。退出码0为ok/ready/empty，3为partial/blocked/
queued/running，2为unsupported/failed/error。未接入模块会明确blocked，不造成功答案。

`fixtures/toy_v1`全为合成来源，含3条Decision、声明与关闭事件、同commit不同原样tag、
两份File、普通评论/review/inline回复及分页缺失。它只验证程序约定，不代表真实LLM或项目事实。
macOS已实际运行；Windows CI的原生数据库冻结重建记录见repro/README.md，不等于成员电脑在线采集或字体检查。

## 全量试跑

`full_history_v1` 是显式选择的试跑档。它沿 GitHub 分页读取公开 Issue、PR 和讨论，
并冻结公开发布、标签和默认分支提交。代码收集遍历默认分支与标签可达的提交，对比第一父提交，
保存变更前后 Python 文件和默认分支／标签快照。对合并提交也使用第一父提交；其他分支、已删除
对象和未合并 PR 的独立提交不在 Git 遍历范围内。原有 `course_small_v1` 默认档、冻结数据
和模型账本保持原语义。

```sh
python -m historykg.cli --config /本机/全量试跑.json build https://github.com/pallets/itsdangerous --profile full_history_v1 --prepare-only
python -m historykg.cli --config /本机/全量试跑.json build-status JOB_ID
python -m historykg.cli --config /本机/全量试跑.json resume JOB_ID
```

全量试跑使用有权限的 GitHub 只读凭据。采集计入分页与重试；成功响应持久保存，限流可继续。
`--prepare-only` 完成静态分析并返回 `extract_estimate_ready`，没有模型调用。
`job.usage.estimate` 给出首轮请求数、估算费用与按峰价无缓存的单次尝试保守上界；
两种费用都不作为付费额度。准备阶段遇到中断时，`resume` 会先继续准备并停在估价；
估价就绪后再调用 `resume` 才进入模型抽取。实际覆盖可从 `snapshot/plan.json`、
`collection/capture.json` 和代码阶段 `plan.json` 对账。

已获运营者授权以 API 账户余额为边界时，在专用试跑配置的 `budget` 中设
`{"mode":"provider_balance","ledger_path":"/本机/全量试跑用量.sqlite3"}`，
只供本轮抽取和验收问答共用。用量照常记录。余额不足时构建返回
`provider_balance_exhausted` 并停在当前阶段；充值后用同一任务号续跑。
已完成抽取直接复用，401 认证失败和 402 余额不足分别诊断。原有有额度的账本不能切换到该模式。
