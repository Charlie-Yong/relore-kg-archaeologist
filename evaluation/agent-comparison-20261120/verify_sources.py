"""Resolve the predefined answer key against original frozen records, plus upstream ancestry."""
import json
from pathlib import Path
import httpx
from run import DATA,HERE,LOCAL,P,save
src=[json.loads(l) for l in DATA.open()]
def api(suffix):
    url='https://api.github.com/repos/pallets/itsdangerous/'+suffix
    return next(json.loads(s['text']) for s in src if s['url']==url and s['kind']=='api_response')
rl=api('releases')
releases=[{'tag':r['tag_name'],'published':r['published_at'],'url':r['html_url'],'prerelease':r['prerelease']} for r in rl]
rels=[r for r in releases if not r['prerelease'] and r['published']<P['cutoff_utc']]
pr=api('pulls/107');p405=api('pulls/405')
changed=next(json.loads(s['text']) for s in src if s['kind']=='git_output' and '"--name-status"' in s['text'][:550] and pr['merge_commit_sha'] in s['text'][:550])
issue=next(s for s in src if s['kind']=='issue_body' and s['url'].endswith('/issues/106'))
answers={'releases':releases,'q1':next(r for r in rels if r['tag']=='2.1.1'),'q2':{'issue':issue['text'],'issue_url':issue['url'],'pr':pr['html_url'],'pr_text':pr['body'],'sha':pr['merge_commit_sha'],'diff_url':'https://github.com/pallets/itsdangerous/commit/'+pr['merge_commit_sha'],'changed_paths':changed['stdout'].split('\x00')},'q3':{'pr_url':p405['html_url'],'sha':p405['merge_commit_sha'],'merged':p405['merged_at'],'latest_formal':max(rels,key=lambda r:r['published']),'ancestry':[]}}
# Test whether the PR merge SHA is an ancestor of the frozen formal release tags.
for r in rels:
 url='https://api.github.com/repos/pallets/itsdangerous/compare/'+p405['merge_commit_sha']+'...'+r['tag']
 try:
  reply=httpx.get(url,timeout=20);j=reply.json()
  answers['q3']['ancestry'].append({'tag':r['tag'],'url':url,'http':reply.status_code,'status':j.get('status'),'merge_base':j.get('merge_base_commit',{}).get('sha')})
 except Exception as ex:answers['q3']['ancestry'].append({'tag':r['tag'],'url':url,'error':type(ex).__name__})
save(HERE/'reference.json',answers)
print(len(rels),answers['q3']['ancestry'])
