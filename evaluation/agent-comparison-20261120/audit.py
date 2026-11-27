"""Verify paired contexts, collect actual per-attempt usage, and check all deliverables."""
import csv,hashlib,json,re
from run import HERE,LOCAL,P,save
def read(p):return json.loads(p.read_text())
def digest(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
summary=[]; pairs={}
for q in range(1,4):
 group={}
 for arm in 'ABCDEF':
  id=f'{arm}{q}';r=read(HERE/'records'/f'{id}.json')
  if arm in 'DE':
   u=(r.get('usage') or [{}])[-1]
   summary.append([id,r['status'],r['elapsed_seconds'],u.get('input_tokens'),u.get('output_tokens'),u.get('reasoning_output_tokens'),'Codex turn.completed'])
   if r['status']=='ok':assert r['answer'].strip()
   continue
  req=next((LOCAL/id).glob('answers/**/request.json'));msgs=read(req)['body']['messages']
  data=json.loads(msgs[1]['content']);group[arm]=digest(data['context'])
  if arm=='C':assert data['graph_edges']==r['graph_edges'] and data['graph_edges']
  assert read(req)['body']['thinking']['type']==('disabled' if arm=='F' else 'enabled')
  if arm!='F':assert read(req)['body']['reasoning_effort']=='max'
  us=[v['usage'] for v in r['responses'] if v.get('usage')]
  assert all(v.get('model')=='bailian/deepseek-v4.1-flash-1017' for v in r['responses'])
  summary.append([id,r['status'],r['elapsed_seconds'],sum(v['prompt_tokens'] for v in us),sum(v['completion_tokens'] for v in us),sum(v.get('completion_tokens_details',{}).get('reasoning_tokens',0) for v in us),'百炼模型响应'])
 assert group['B']==group['C']==group['F']
 pairs[str(q)]=group
with (HERE/'调用与耗时.csv').open('w',encoding='utf-8-sig') as f:
 w=csv.writer(f);w.writerow(['组及题','系统状态','完整等待秒','输入token','输出token','其中推理token','用量依据']);w.writerows(summary)
save(HERE/'diagnostics/context-hashes.json',pairs)
ret=LOCAL/'direct-retired'
prior=[f for f in ret.glob('*/answers/**/attempts/*/response.json')]
pilot=list((LOCAL/'pilot-v2').glob('answers/**/attempts/*/response.json'))
# No credentials, headers, raw reasoning or private workdirs in public deliverables.
note=f'''# 运行过程与复核入口

1. 固定 ItsDangerous 数据集 {P['head']} 对应的仓库版本、三道题、截止时间和评分项。共同题干在 protocol.json，评分前用于查证的字段及原始链接在 reference.json。
2. 恢复 11 月 16 日的 Neo4j 和冻结索引。旧凭据发生 401。新凭据连通后开始直连，在用户指定百炼时停止。切换前留存 {len(prior)} 份直连正式题响应、{len(pilot)} 份直连预检响应，仅作过程记录，均未进入表格。可能已有发送但未取得响应的调用，不能据此断言旧账户零费用。正式结果全部采用已配置的百炼入口。
3. 百炼开关预检回执为 preflight-enabled.json 和 preflight-disabled.json。A/B/C 调用同一 Chat Completions 模型，D/E 用 Codex 的同名百炼模型、每题独立会话及 max 档，F 复用 B 原文并关闭思考。三题 B/C/F 的原文逐字散列相同，见 diagnostics/context-hashes.json。
4. 每题独立计时并保留首次作答。records 中保留用户实际收到的结果。API 类记录另附完整原始模型回答（不含内部思考文本）和每次模型返回的用量；Agent 类记录保留完整作答、操作摘要与来源。调用与耗时.csv 汇总十八次运行；用量采用该接口返回口径。并行运行造成 A1 账本冲突，报告保留首答错误。
5. 评审只收到随机编号、原答、标准事实与题目，隐藏组名及时间。scores 对应三题逐项评分。第三题初评存在结论混淆，原始评分见 diagnostics/q3-anonymous-original.json，公开表使用逐项核对后的 scores/q3.json。额外检查含六个正式发布标签的可达性和默认检索的原文；诊断另列，不覆盖原始分数。

## 文件用途

- 实验报告.md 结合匿名评分、原文及初次计时做逐题解释。课堂汇报.pdf 用于单页放映。
- run.py 为实际入口，使用现有的冻结作业与本机配置的百炼通道。正式档案已封存；独立复现请在工作副本中使用新记录目录和独立账本，避免复用缓存或并行写入相同请求标识。
- assess.py 为匿名评审与原答整理；verify_sources.py 核对来源及祖先关系；audit.py 汇总用量并断言三组原文一致；report.py 生成报告与课堂页。
'''
(HERE/'过程记录.md').write_text(note)
print('audited',len(summary),'results;',len(pairs),'paired contexts')
