from html import escape
from run import HERE,LOCAL,P,save
import json
def read(p):return json.loads(p.read_text())
records={p.stem:read(p) for p in (HERE/'records').glob('*.json')}
scores={}
for n in range(1,4):scores.update(read(HERE/'scores'/f'q{n}.json')['scores'])
m=[2,5,4]
names={'A':'API · 文本检索','B':'API · 图辅助检索','C':'API · 原文加图关系','D':'Codex · 本地原文','E':'Codex · GitHub','F':'API · 图检索关闭思考'}
def pts(a,i):return sum(scores[a+str(i)]['points'])
def secs(a,i):return records[a+str(i)]['elapsed_seconds']
def cell(a,i):return f"{pts(a,i):g}/{m[i-1]} · {secs(a,i):.1f} 秒"+(' †' if secs(a,i)>300 else '')
def total(a,t=999):return sum(pts(a,i) for i in range(1,4) if secs(a,i)<=t)
def differences(left,right):
 return '、'.join(f'{secs(left,i)-secs(right,i):+.1f}' for i in range(1,4))+' 秒'
rows=[[names[a],*[cell(a,i) for i in range(1,4)],f'{total(a,300):g} / {total(a):g}'] for a in names]
header=['方法','发布日期（2项）','重构追溯（5项）','版本归属（4项）','5分钟 / 最终得分（各11）']
def mdtable(h,rs):return '\n'.join(['| '+' | '.join(h)+' |','| '+' | '.join('---' for _ in h)+' |',*['| '+' | '.join(x)+' |' for x in rs]])
more=[]
for i in range(1,4):
 more+=['### '+str(i)+'. '+P['questions'][i-1],'','逐项顺序为 '+'、'.join(P['rubric'][i-1])+'。','']
 for a in names:
  id=a+str(i);s=scores[id];r=records[id]
  more.append(f"- **{names[a]}**　{' / '.join(str(x) for x in s['points'])}。{s['note']} 用时 {secs(a,i):.1f} 秒，状态 {r['status']}。[原始回答与引用](records/{id}.json)")
 more.append('')
out=f'''# 同一 DeepSeek 模型怎样查开源项目历史
## ItsDangerous · 2026 年 11 月 20 日

3 道题共有 11 个预设查证项。本地原文 Agent 最终获得 **{total('D'):g}/11**，GitHub Agent 获得 **{total('E'):g}/11**，HistoryKG 默认图检索获得 **{total('B'):g}/11**。发布日期题两种 Agent 都找到了正式发布原文，本地等待 {secs('D',1):.1f} 秒，在线等待 {secs('E',1):.1f} 秒。五分钟内能交付的成绩和延长等待后的成绩分别列出。

'''+mdtable(header,rows)+f'''

单元格为有据得分与本次运行返回用时。† 表示超过 300 秒。单题最长等待 600 秒，错误或超时按未交付处理。每个事实项完全满足得 1 分，部分满足得 0.5 分。每组每题仅测一次。

## 哪些差异能从结果中看出来

- **图辅助检索。** 第二题普通检索得 {pts('A',2):g}/5，图辅助检索得 {pts('B',2):g}/5。后者找到了 Issue #106 对拆分模块和测试的说明。要证明改动确已实施，还需追到 PR #107 和相应 diff，当前源码的单一快照难以提供这条历史链。
- **直接给图。** C 和 B 逐题得分为 {', '.join(f'{pts("C",i):g} 对 {pts("B",i):g}' for i in range(1,4))}。C 逐题额外加入同一次图检索中的 10 条有向边，回答器仍须引用与 B 相同的原文。C 相对 B 的耗时差为 {differences('C','B')}。关系链的相关性和附加输入长度都会影响结果。
- **本地与在线。** 重构题分别为本地 {cell('D',2)}、在线 {cell('E',2)}。版本题分别为本地 {cell('D',3)}、在线 {cell('E',3)}，本地组额外拿出了 tag 提交历史的证据。在线相对本地逐题多等 {differences('E','D')}，后两题超过五分钟。等待时间包含启动、工具调用、网络和排错。
- **推理开关。** 图检索开启和关闭思考的总分分别为 {total('B'):g} 与 {total('F'):g}。三个问题开启减关闭耗时分别为 {', '.join(f'{secs("B",i)-secs("F",i):+.1f}' for i in range(1,4))} 秒。发布日期题的可见材料主要是测试代码，增加推理无法补齐缺失的发布记录。
- **预处理。** 已有图从 11 月 16 日 14:31:18 至 15:10:32 构建，墙钟 39 分 14 秒，包含采集、抽取、索引和作业间隔。历史抽取账本约 2.85 元。本地原文组也复用了已采数据，复制语料在计时开始前完成。本轮用量来自两种接口的回执。Codex 的多轮输入包含重复上下文及缓存用量，用量表中的 token 用于复核，人民币费用缺少独立账单。

## 逐题核查

'''+ '\n'.join(more)+'''

## 可复核的标准事实

1. 2.1.1 的 published_at 为 2022-03-09 16:25:33 UTC。[GitHub Release](https://github.com/pallets/itsdangerous/releases/tag/2.1.1)
2. Issue #106 指出代码虽已改成包，仍集中在 __init__.py，测试也只有一个文件。PR #107 合并为 8e611d7373acc874cc8bd3fc480cf3cf7b5b6a10。可核对的实例包括新增 signer.py，删除 tests/test_itsdangerous.py 并新增 tests/test_signer.py 等专用测试。[Issue](https://github.com/pallets/itsdangerous/issues/106) · [PR](https://github.com/pallets/itsdangerous/pull/107) · [提交差异](https://github.com/pallets/itsdangerous/commit/8e611d7373acc874cc8bd3fc480cf3cf7b5b6a10)
3. PR #405 于 2025-05-28 合并为 4dffa1963f896a0a311dec3c14f003a5f382c446。冻结清单最新正式 Release 为 2024-04-16 的 2.2.0。用六个正式发布标签逐个作 GitHub compare（合并 SHA 为 base，tag 为 head），均得到 behind，因此这六个标签均未包含该合并提交。该结论限截止日的 GitHub 正式发布与 Git 祖先关系。[PR](https://github.com/pallets/itsdangerous/pull/405) · [2.2.0 对比](https://github.com/pallets/itsdangerous/compare/4dffa1963f896a0a311dec3c14f003a5f382c446...2.2.0) · [六条核查回执](reference.json)

## 过程、计时与限制

- **冻结题目。** 先冻结三道中文题、查证项、截止时间 2026-11-16 06:31:18 UTC 和仓库版本，再作答。旧 Flask 分数仅作历史参考。全部正式答案均走百炼 DeepSeek-V4.1-Flash-1017。A/B/C 和两个 Agent 请求 max，F 请求关闭，同一道预检问题开启和关闭分别观察到 93 和 0 个推理 token。请求档位与服务端计量分别记录。
- **输入。** API 三组使用同一回答提示，原文预算 12,000 字符，最多输出 8,192 token，单次请求超时 90 秒，允许两次重试。C 额外展示 B 的图边。D 提供 7,417 条冻结来源，追踪记录只观察到本地文件工具。E 从空目录启动，实际通过可用网页工具查找公开 GitHub 来源。每题独立会话，主要区别是整套工作流，覆盖范围、工具和上下文规模各有差异。
- **故障。** 早期直连凭据失效，更新后曾经启动直连批次；改用百炼时停止，其答案和用量不进入正式比较。百炼 A1 与 B1 并行时发生相同请求的账目结算冲突。A1 原始模型响应为空答，系统向用户返回错误，保留首次记录。并发、检索缓存及网络状态可能影响时间。F 组作为附加试验，用来观察开启思考对固定原文场景的影响。
- **日期题诊断。** B 的三个可见原文片段都是冻结 SHA 下的测试代码。另做一次事后免费检索，去掉题干中的仓库与 SHA，让数据集本身限定范围；仍未取到正式发布日期。下一版优先给发布日期题查 Release 的 published_at，给历史修改题沿 PR→提交→diff 找原文，然后用新题检验。[实际片段与诊断](diagnostics/)
- **匿名评审。** 每题将答案随机改为编号，去掉系统名、耗时和模型标记。用单独、无工具的百炼调用按参考事实初评，之后回看原答和来源。第三题初评错把缺证组当作已给出合并与发布事实，逐项复核后纠正。对明确说明合并 SHA 与发布标签需要怎样对应的缺证答案，版本结论项给部分分。第三题初评在思考耗尽输出后改为关闭思考，正式答题结果保留。回答风格可能暴露系统类型。本表是模型初评加逐条原文核查，未进行人类双盲评审。[第三题初评](diagnostics/q3-anonymous-original.json) · [第三题审定](scores/q3.json)本表适用于三个具体案例。

[题干和时限](protocol.json) · [原始回答](records/) · [评分细目](scores/) · [用量与计时](调用与耗时.csv) · [过程记录](过程记录.md) · [推理开启回执](preflight-enabled.json) · [关闭回执](preflight-disabled.json)
'''
(HERE/'实验报告.md').write_text(out)
table='<table><thead><tr>'+''.join('<th>'+escape(h)+'</th>' for h in header)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table>'
html='''<!doctype html><meta charset="utf-8"><style>@page{size:320mm 180mm;margin:0}*{box-sizing:border-box}body{width:320mm;margin:0;padding:9mm 13mm;font-family:"PingFang SC",sans-serif;color:#122536}small{color:#35675c;font-size:14px}h1{margin:10px 0 4px;font-size:33px}p{font-size:17px;margin:7px 0}table{width:100%;border-collapse:collapse;margin:16px 0}td,th{font-size:16px;text-align:left;padding:8px 9px;border-bottom:1px solid #c9d4dc}th{background:#eaf0ed}p.foot{font-size:14px;color:#364956}</style><small>知识图谱课程项目　｜　ItsDangerous　｜　2026.11.20</small><h1>同一模型查项目历史，质量与等待时间有何差别？</h1><p>百炼 DeepSeek‑V4.1‑Flash‑1017　·　三道预先固定的问题　·　每组每题一次</p>'''+table+f'''<p><b>发布日期题</b>　两种 Agent 都答对，本地 {secs('D',1):.0f} 秒，在线 {secs('E',1):.0f} 秒。图检索返回了测试代码。</p><p><b>重构追溯题</b>　普通检索 {pts('A',2):g}/5，图检索 {pts('B',2):g}/5，本地 Agent {pts('D',2):g}/5，在线 Agent {pts('E',2):g}/5。</p><p><b>版本归属题</b>　本地 Agent {pts('D',3):g}/4，核对了 tag 历史。在线 Agent {pts('E',3):g}/4，查到了合并和正式发布记录。</p><p class="foot">每格为证据项得分与墙钟耗时。† 超过 5 分钟，单题最长等待 10 分钟。A 的日期题发生结算错误。预建图耗时 39 分 14 秒。<br>按预设事实逐项核查，模型匿名初评后复核。每组各测三题。</p>'''
(HERE/'课堂汇报.html').write_text(html)
