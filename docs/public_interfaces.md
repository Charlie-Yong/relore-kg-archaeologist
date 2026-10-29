# 公共数据和构建接口

P1维护，契约1.4.1。输入是公开GitHub Python仓库URL，正常建图不填线程号、SHA或路径。
上游采集与固定relore移植归P4，代码版本事实归P3，Decision归P4，图/检索归P2。

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
当前实际平台为macOS，Windows命令待实机验证。
