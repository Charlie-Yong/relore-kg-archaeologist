"""Run the frozen six-arm experiment. Raw tool traces/requests stay in .local."""
import concurrent.futures, datetime, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time
from pathlib import Path
from threading import Lock
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from historykg import pipeline
from historykg.query import query
from historykg.query.service import prepare_query
from historykg.llm import answer as ans
from historykg.llm.answer import render_context
from historykg.llm.gateway import prepare_request
P=json.loads((HERE/'protocol.json').read_text())
TRIAL=ROOT/'.local/full-history-itsdangerous'
LOCAL=ROOT/'.local/comparison-20261120'
LOCAL.mkdir(exist_ok=True)
CFG=json.loads((TRIAL/'project.json').read_text())
DATA=next((TRIAL/'datasets').glob('*/sources.jsonl'))
ID='dataset:'+DATA.parent.name.split('-',1)[1]
def save(p,v):
    p.parent.mkdir(exist_ok=True,parents=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2))
import tomllib
import httpx
from contextlib import contextmanager
from historykg.llm.gateway import run_request as gateway_call
ROUTE='bailian/deepseek-v4.1-flash-1017'
class BailianTransport(httpx.BaseTransport):
    def handle_request(self,request):
        # Only the locally configured desktop relay receives its own auth header.
        settings=tomllib.loads((Path.home()/'.codex/config.toml').read_text())['model_providers']['magpie']
        base=settings['base_url']
        if not base.startswith('http://127.0.0.1:'):raise ValueError('Expected loopback relay')
        payload=json.loads(request.content)
        payload['model']=ROUTE
        thinking=payload['thinking']['type']=='enabled'
        payload['enable_thinking']=thinking
        payload['reasoning_effort']='max' if thinking else 'none'
        headers={**settings.get('http_headers',{}),'Authorization':'Bearer '+settings['experimental_bearer_token']}
        with httpx.Client(trust_env=False,timeout=90) as client:
            resp=client.post(base+'/chat/completions',json=payload,headers=headers)
        return httpx.Response(resp.status_code,content=resp.content,headers={'content-type':'application/json'})
def via_bailian(*args,**kwargs):
    return gateway_call(*args,**kwargs,transport=BailianTransport())
def question(i):
    return f"仓库 {P['repo']}，截止时间 {P['cutoff_utc']}，冻结默认分支 {P['head']}。"+P['questions'][i]
def runner(arm,i):
    ident=f'{arm}{i+1}'
    out=HERE/'records'/f'{ident}.json'
    if out.exists():return
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    if arm in 'DE':
        env=os.environ.copy()
        work=Path(tempfile.mkdtemp(prefix='itsdangerous-bench-'))
        if arm=='D':
            shutil.copyfile(DATA,work/'sources.jsonl')
        raw=LOCAL/ident;raw.mkdir(exist_ok=True)
        task=question(i)+' 用中文直接给出回答、可核对的原文或字段与官方出处链接。'
        task+=('独立以当前目录 sources.jsonl 中冻结的原始材料作答。每行是 JSON，含 kind/url/text。只用 shell 在当前目录查阅，不访问网络、其他目录或历史答案。' if arm=='D' else '只使用终端通过公开 GitHub API、GitHub 原文或 git 自行调查。可用 curl、python、git。仅使用截止日前已公开资料；不要读取工作区以外的文件。')
        args=['codex','exec','--ephemeral','--skip-git-repo-check','--json','-C',str(work),'-s','workspace-write','-m','bailian/deepseek-v4.1-flash-1017']
        for v in ['model_provider="magpie"','model_reasoning_effort="max"','sandbox_workspace_write.network_access='+('true' if arm=='E' else 'false'),'web_search="disabled"']:
            args+=['-c',v]
        args+=['-o',str(raw/'answer.txt'),task]
        t=time.monotonic()
        with (raw/'events.jsonl').open('w') as stdout,(raw/'stderr.txt').open('w') as err:
            proc=subprocess.Popen(args,stdout=stdout,stderr=err,cwd=work,env=env,start_new_session=True)
            try:code=proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(proc.pid,signal.SIGTERM);code=124
        elapsed=time.monotonic()-t
        text=(raw/'answer.txt').read_text() if (raw/'answer.txt').exists() else ''
        events=[]
        for line in (raw/'events.jsonl').read_text().splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        res={'status':'ok' if code==0 and text else 'timeout' if code==124 else 'error','answer':text,'exit':code,'tools':[e['item'].get('command') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='command_execution'],'usage':[e.get('usage') for e in events if e.get('usage')],'event_types':sorted(set(e.get('type','') for e in events)),'prompt':task}
        shutil.rmtree(work)
    else:
        os.environ['DEEPSEEK_API_KEY']='local-relay-routing-only'
        ans.run_request=via_bailian
        cfg=pipeline.query_config(CFG)
        cfg['budget']={'mode':'provider_balance','ledger_path':str(LOCAL/'bailian-estimates.sqlite3')}
        cfg.update(system='A' if arm=='A' else 'B',query_output_root=str(LOCAL/ident/'queries'),answer_output_root=str(LOCAL/ident/'answers'))
        cfg['answer']={**CFG['model'],'thinking':'disabled' if arm=='F' else 'enabled','reasoning_effort':'max','max_output_tokens':8192,'timeout_seconds':90,'max_retries':2}
        req={'dataset_id':ID,'question':question(i),'kind':'search'}
        t=time.monotonic()
        prep=prepare_query(req,config=cfg) if arm=='C' else None
        if prep:
            # Only expose graph edges backed by the same visible source passages.
            vis=render_context(prep['candidates'],max_characters=12000)['fragments']
            ev={e['evidence_id']:e for e in prep['path_evidence']}
            edges=[]
            for path in prep['paths']:
                for r in path['relations']:
                    hits=[eid for eid in r.get('evidence_ids',[]) if eid in ev and any(f['source_id']==ev[eid]['source_id'] and f['start']<=ev[eid]['start'] and ev[eid]['end']<=f['end'] for f in vis)]
                    if hits or len(edges)<10:
                        nodes={n['id']:n for n in path.get('entities',[])}
                        def label(k):
                            o=nodes.get(k,{});p=o.get('properties',{});return p.get('display_name') or p.get('title') or p.get('path') or p.get('tag') or p.get('number') or k
                        edge=[label(r['from_id']),r['type'],label(r['to_id']),(ev[hits[0]]['source_id'] if hits else '图关系，须由可见原文另行验证')]
                        if edge not in edges:edges.append(edge)
            def wrapper(**kwargs):
                kwargs['payload']={**kwargs['payload'],'graph_edges':edges}
                return prepare_request(**kwargs)
            # Avoid re-running retrieval in timed C. Include edge preparation.
            with patch.object(ans,'prepare_request',wrapper),patch('historykg.query.service.prepare_query',return_value=prep):
                result=query(req,config=cfg)
        else:result=query(req,config=cfg)
        elapsed=time.monotonic()-t
        val=result.model_dump(mode='json');save(LOCAL/ident/'result.json',val)
        refs={e['evidence_id']:e for e in val.get('evidence',[])}
        res={k:val.get(k) for k in ['claims','status','gaps','error','usage','model_run_id']}
        res['evidence']=[refs[e] for e in dict.fromkeys(e for c in res['claims'] for e in c['evidence_ids'])]
        res['paths_count']=len(val['paths']);res['graph_edges']=edges if prep else None
    save(out,{'arm':arm,'q':i+1,'start_utc':now,'elapsed_seconds':round(elapsed,3),**res})
    print(ident,res['status'],round(elapsed,1),flush=True)
if __name__=='__main__':
    for arm in sys.argv[1]:
        for i in range(3):
            runner(arm,i)
