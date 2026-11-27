"""Blind factual assessment. Keep the randomized mapping outside the judge's input."""
import hashlib,json,random,time,re
from pathlib import Path
from run import HERE,LOCAL,P,BailianTransport,save,httpx
def files(id):
 return sorted((LOCAL/id).glob('answers/**/attempts/*/response.json'))
def exported(id,j):
 original=j.copy()
 if id[0] in 'DE':
  events=[json.loads(l) for l in (LOCAL/id/'events.jsonl').open() if l.strip()]
  actions=[]
  for ev in events:
   it=ev.get('item') or {}
   if ev['type']!='item.completed' or it.get('type') not in ('command_execution','mcp_tool_call'):continue
   arg=it.get('arguments',{})
   # Publish actions and GitHub URLs, never unrestricted command outputs.
   actions.append({'tool':it.get('tool',it['type']),'title':arg.get('title',''),'urls':sorted(set(re.findall(r'https?://(?:api\.github\.com/repos|github\.com|raw\.githubusercontent\.com)/pallets/itsdangerous[^\s"\\<>\x27]*',json.dumps(arg))))[:12]})
  j['actions']=actions;j['wall_clock_includes_launch']=True
 else:
  responses=[]
  for f in files(id):
   obj=json.loads(f.read_text());v=json.loads(obj['body']);choice=v.get('choices',[{}])[0]
   raw=choice.get('message',{}).get('content')
   responses.append({'attempt':f.parent.name,'http':obj['status_code'],'model':v.get('model'),'finish_reason':choice.get('finish_reason'),'usage':v.get('usage'),'raw_answer':raw})
  j['responses']=responses
  if len(json.dumps(j.get('gaps'))) >10000:
   allg=j.pop('gaps');j['gap_counts']={t:sum(1 for k in allg if isinstance(k,t0)) for t,t0 in [('metadata',dict),('message',str)]}
   j['answer_gaps']=[k for k in allg if isinstance(k,str)][-15:]
   j['full_result_local']=f'.local/comparison-20261120/{id}/result.json'
  if j.get('usage'):
   j['usage']={k:v for k,v in j['usage'].items() if 'cny' not in k}
 save(HERE/'records'/f'{id}.json',j)
 return j
def assess(n):
 out=HERE/'scores'/f'q{n}.json'
 if out.exists():return
 ref=json.loads((HERE/'reference.json').read_text());truth=ref[f'q{n}']
 ids=[a+str(n) for a in 'ABCDEF']
 random.Random(20261120+n).shuffle(ids)
 answers={}
 for pos,id in enumerate(ids):
  j=exported(id,json.loads((HERE/'records'/f'{id}.json').read_text()))
  if 'answer' in j:content=j['answer'] or '未交付答案'
  elif j['status']=='error':content='未交付答案'
  else:content={'answer':j['responses'][-1]['raw_answer'] if j['responses'] else j.get('claims',[]),'urls':[e['url'] for e in j.get('evidence',[])]}
  answers[str(pos+1)]=content
 prompt={'question':P['questions'][n-1],'criteria':P['rubric'][n-1],'reference':truth,'answers':answers}
 system='你是匿名事实核对员。按给定 criteria 的顺序逐项判断，可核对原文或官方链接且完全正确给1；仅部分事实、无对应出处或仅给局部依据给0.5；遗漏或错误给0。第2题需要具体历史变化，而非后来版本的单个快照或计划。第3题合并后没有可证实的正式发布：应有实际合并、发布清单和版本包含关系分别支撑。纯泛泛说材料不足不算证实。仅返回 JSON 对象，键为匿名编号，值为 {"points":[数字...],"note":"中文一句具体判断"}。不要额外输出。'
 body={'model':'deepseek-flash','messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(prompt,ensure_ascii=False)}],'response_format':{'type':'json_object'},'thinking':{'type':'disabled' if n==3 else 'enabled'},'max_tokens':8192}
 save(LOCAL/f'blind-input-{n}.json',prompt)
 for attempt in range(4):
  try:
   result=BailianTransport().handle_request(httpx.Request('POST','https://unused',json=body))
   doc=result.json()
   if 'choices' not in doc:
    print('judge HTTP',result.status_code,str(doc.get('error',''))[:160],flush=True);time.sleep(2);continue
   content=doc['choices'][0]['message']['content']
   val=json.loads(content);break
  except (ValueError,httpx.HTTPError,IndexError,TypeError) as exc:
   print('judge retry',type(exc).__name__,flush=True);time.sleep(2)
 else:raise RuntimeError('No valid judge response')
 for pos,id in enumerate(ids):
  pts=val[str(pos+1)]['points'];assert len(pts)==len(P['rubric'][n-1]) and all(p in [0,0.5,1] for p in pts)
 save(out,{'method':'同一百炼模型独立无工具匿名评审，逐项计分；可按 reference.json 复查','judge_thinking':'disabled' if n==3 else 'enabled','question':n,'rubric':P['rubric'][n-1],'scores':{id:val[str(i+1)] for i,id in enumerate(ids)}})
 print('assessed',n,flush=True)
if __name__=='__main__':
 pending={1,2,3}
 while pending:
  for n in sorted(pending.copy()):
   if all((HERE/'records'/f'{a}{n}.json').exists() for a in 'ABCDEF'):
    assess(n);pending.remove(n)
  if pending:time.sleep(4)
