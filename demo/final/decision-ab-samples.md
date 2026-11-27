# 无编号历史决策题的 A/B 原文对照

A 和 B 共用冻结来源、关键词与逐字引文提示。下表记录同一原文区间是否完整进入两组的 12,000 字符输入。共同列表的排名、B 的取证来源与裁剪结果见 JSON。

## 为什么改用标准库 JSON？早期有没有拒绝过类似提议，最终由哪个 PR 合并落地并改了哪些文件？

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–195。[出处](https://github.com/pallets/itsdangerous/pull/63#issuecomment-226116816)

> It won't result in an error if simplejson is installed.  The point of the linked issue is that the name `simplejson` is not exported, it's always aliased to `json`.  Nothing needs to change here.

- **A 可见，B 可见**。共同检索 2，B 经图谱关系找到原文。两组都可见。原文区间 0–99。[出处](https://github.com/pallets/itsdangerous/issues/146)

> itsdangerous and by extension flask, starlette, and others use simplejson if it's installed due to:

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 有完整候选但预算用尽，片段排序影响可见性。原文区间 0–337。[出处](https://github.com/pallets/itsdangerous/issues/146#issuecomment-590060970)

> ``json`` was added to Python 2.6, so the main reason to use ``simplejson`` is backwards compatibility with Python 2.4+ (although, as someone who occasionally has to maintain Python 2.4 code, the sooner it dies the better).
> 
> Considering the oldest test suite on this project runs on Python 2.7, it seems a good candidate to refactor this.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–52。[出处](https://github.com/pallets/itsdangerous/issues/146#issuecomment-592275222)

> Yeah, I'm fairly ok with this once we drop Python 2.

- **A 可见，B 可见**。共同检索 1，B 经图谱关系找到原文。两组都可见。原文区间 0–214。[出处](https://github.com/pallets/itsdangerous/pull/152)

> Removes simplejson in favor of Python's built-in json module. Since `itsdangerous.json` would just be an alias for that module now, it's replaced with an proxy that raises a deprecation warning on use.
> 
> closes #146

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 16971–17126。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/63)

> "merge_commit_sha": "105caae4a52c97c1b95d17a0ca956eb56cc7f31b",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": false,
>   "merged_at": null,

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 17262–17434。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/152)

> "merge_commit_sha": "981ade6e73ff9ce420aa29143039de0aaccb9770",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": true,
>   "merged_at": "2020-04-17T17:15:12Z",

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 Git 差异回查。A 没有覆盖该区间的候选。原文区间 0–467。[出处](https://github.com/pallets/itsdangerous/commit/981ade6e73ff9ce420aa29143039de0aaccb9770)

> {
>   "command": [
>     "git",
>     "diff-tree",
>     "--no-commit-id",
>     "-r",
>     "-M",
>     "--name-status",
>     "-z",
>     "542fad1e9627a402620453610b3e6923f879fd84",
>     "981ade6e73ff9ce420aa29143039de0aaccb9770"
>   ],
>   "returncode": 0,
>   "stdout": "M\u0000CHANGES.rst\u0000M\u0000docs/serializer.rst\u0000M\u0000src/itsdangerous/__init__.py\u0000M\u0000src/itsdangerous/_json.py\u0000M\u0000src/itsdangerous/jws.py\u0000M\u0000src/itsdangerous/serializer.py\u0000"
> }

## 项目历史上有哪些被拒绝的特性提案及理由？

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–277。[出处](https://github.com/pallets/itsdangerous/pull/1)

> Howdy!
> 
> I've added marrow.templating support; one simple function, an entry point, and no additional dependencies.
> 
> Additionally, dump[s] commands now accept additional keyword arguments which are then passed to json.dumps, allowing you to control the serialization formatting.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–337。[出处](https://github.com/pallets/itsdangerous/pull/1#issuecomment-1434107)

> I don't want to step into that particular direction with the library for the time being. Instead why not have a second library that implements the entrypoints for marrow if that is necessary? I still remember the last attempt of an unified templating language API and it was horrible, I don't want to be involved with that a second time.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–280。[出处](https://github.com/pallets/itsdangerous/issues/25)

> Especially since this is based on Django's signing module.
> 
> Alternatively, you could let us set a default secret key to use, which would be the more generally useful implementation.
> 
> It's just not very DRY to pass this information in everywhere that you use a signer in your code.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–167。[出处](https://github.com/pallets/itsdangerous/issues/25#issuecomment-21777893)

> Itsdangerous is a separate library and has nothing to do with django.  Definitely not going to add magic that kicks in if the library is used in a certain environment.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–283。[出处](https://github.com/pallets/itsdangerous/issues/26#issuecomment-23160780)

> I am familiar with the attack.  Itsdangerous signs, it does nothing else.  Whatever SSL does it out of the focus of this library.  Add a random salt to your data payload if you want to defeat that.  I believe that this issue should be solved on the SSL layer and not in itsdangerous.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–118。[出处](https://github.com/pallets/itsdangerous/issues/28#issuecomment-23477269)

> Hmm. Wondering if that is a problem or not.  The only thing that you changed is the transport format, not the payload.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–365。[出处](https://github.com/pallets/itsdangerous/issues/28#issuecomment-41691783)

> I don't see this as a security issue as the whole point of itsdangerous is to verify a payload was not modified.  We do this by creating a signature that, theoretically, only a trusted user can produce.  In my mind, unless this makes it easier for an attacker to forge signatures or create new signatures based on existing ones, I don't see it as a security threat.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–48。[出处](https://github.com/pallets/itsdangerous/issues/28#issuecomment-41906622)

> OK, so probably this issue can be closed safely.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–22。[出处](https://github.com/pallets/itsdangerous/issues/28#issuecomment-106736453)

> ACK, should be closed.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–397。[出处](https://github.com/pallets/itsdangerous/issues/11#issuecomment-106739185)

> Well, it might be desirable to differentiate between expired signatures and completely invalid ones. Technically, a signature can't be invalidated by time, either it's valid or it's not. The timestamp is additional payload that is evaluated after the signature proved to be valid.
> 
> Note that `TimestampSigner.validate` also raised `BadTimeSignature` which isn't caught either.
> 
> I would close this.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–220。[出处](https://github.com/pallets/itsdangerous/issues/45)

> if the token is about to expire, I want to call an interface (or any one can point me in correct way) to extend the expiry time of an already issued token. I am using TimedJSONWebSignatureSerializer to create the tokens.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–301。[出处](https://github.com/pallets/itsdangerous/issues/45#issuecomment-148831232)

> It's impossible to provide a facility like that because the expiration time is in the token itself. When you change any value in the token, you get a completely different token. An alternative implementation would be to issue a refresh token that won't expire and use that to issue new primary tokens.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–226。[出处](https://github.com/pallets/itsdangerous/issues/54#issuecomment-161721273)

> I find JWT tricky to use securely which is why I avoid it like the plague whenever I can for my own stuff.  You cannot avoid JWT much for external interoperability obviously but I will not deprecate itsdangerous as a result :)

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–81。[出处](https://github.com/pallets/itsdangerous/pull/10#issuecomment-204765303)

> Closing due to merge conflicts.  Also, rst uses double backticks for inline code.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–71。[出处](https://github.com/pallets/itsdangerous/pull/15#issuecomment-207998674)

> Command seems to work without this.  Thanks for pointing it out though.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–106。[出处](https://github.com/pallets/itsdangerous/pull/13#issuecomment-208001654)

> I timed both versions and there was no significant change, so just going to close this and leave it as is.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–116。[出处](https://github.com/pallets/itsdangerous/pull/27#issuecomment-209080997)

> I'm on board with the exception fix, but why is there an unrelated change that makes invalid data into valid tokens?

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–61。[出处](https://github.com/pallets/itsdangerous/issues/40#issuecomment-209083922)

> This is a good case for writing your own Serializer subclass.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–204。[出处](https://github.com/pallets/itsdangerous/pull/27#issuecomment-209084591)

> It's not unrelated, but I guess the PR's name implies a smaller scope.
> 
> Characters that are invalid base64 are first ignored, then decoding proceeds. Decoding could still fail because of bad data, though.

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。A 没有覆盖该区间的候选。原文区间 0–304。[出处](https://github.com/pallets/itsdangerous/pull/27#issuecomment-209085668)

> That's not something that should happen.  Invalid data is invalid, the fact that removing some characters might produce a valid signature doesn't matter.  If that's something you want to happen, write a custom Serializer subclass (although you should probably fix the thing sending you bad data instead).

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 10873–11028。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/1)

> "merge_commit_sha": "80b9b81f9109ffa64facca0e5d9a7ee0032d9505",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": false,
>   "merged_at": null,

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 10810–10965。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/10)

> "merge_commit_sha": "555d7926d61214cee9272a4eb618ce1bd030f4a5",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": false,
>   "merged_at": null,

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 10596–10751。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/13)

> "merge_commit_sha": "67794a21d1938e1512683ece6d3a04c72c562623",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": false,
>   "merged_at": null,

## 为什么移除了 simplejson？

- **A 可见，B 可见**。共同检索 2，B 经图谱关系找到原文。两组都可见。原文区间 0–195。[出处](https://github.com/pallets/itsdangerous/pull/63#issuecomment-226116816)

> It won't result in an error if simplejson is installed.  The point of the linked issue is that the name `simplejson` is not exported, it's always aliased to `json`.  Nothing needs to change here.

- **A 可见，B 可见**。共同检索 1，B 经图谱关系找到原文。两组都可见。原文区间 0–99。[出处](https://github.com/pallets/itsdangerous/issues/146)

> itsdangerous and by extension flask, starlette, and others use simplejson if it's installed due to:

- **A 可见，B 可见**。共同检索 5，B 经图谱关系找到原文。两组都可见。原文区间 0–337。[出处](https://github.com/pallets/itsdangerous/issues/146#issuecomment-590060970)

> ``json`` was added to Python 2.6, so the main reason to use ``simplejson`` is backwards compatibility with Python 2.4+ (although, as someone who occasionally has to maintain Python 2.4 code, the sooner it dies the better).
> 
> Considering the oldest test suite on this project runs on Python 2.7, it seems a good candidate to refactor this.

- **A 可见，B 可见**。共同检索 未入共同前 20 名，B 经图谱关系找到原文。两组都可见。原文区间 0–52。[出处](https://github.com/pallets/itsdangerous/issues/146#issuecomment-592275222)

> Yeah, I'm fairly ok with this once we drop Python 2.

- **A 可见，B 可见**。共同检索 3，B 经图谱关系找到原文。两组都可见。原文区间 0–214。[出处](https://github.com/pallets/itsdangerous/pull/152)

> Removes simplejson in favor of Python's built-in json module. Since `itsdangerous.json` would just be an alias for that module now, it's replaced with an proxy that raises a deprecation warning on use.
> 
> closes #146

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 16971–17126。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/63)

> "merge_commit_sha": "105caae4a52c97c1b95d17a0ca956eb56cc7f31b",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": false,
>   "merged_at": null,

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 PR API 回查。A 没有覆盖该区间的候选。原文区间 17262–17434。[出处](https://api.github.com/repos/pallets/itsdangerous/pulls/152)

> "merge_commit_sha": "981ade6e73ff9ce420aa29143039de0aaccb9770",
>   "mergeable": false,
>   "mergeable_state": "dirty",
>   "merged": true,
>   "merged_at": "2020-04-17T17:15:12Z",

- **A 缺失，B 可见**。共同检索 未入共同前 20 名，B 经冻结 Git 差异回查。A 没有覆盖该区间的候选。原文区间 0–467。[出处](https://github.com/pallets/itsdangerous/commit/981ade6e73ff9ce420aa29143039de0aaccb9770)

> {
>   "command": [
>     "git",
>     "diff-tree",
>     "--no-commit-id",
>     "-r",
>     "-M",
>     "--name-status",
>     "-z",
>     "542fad1e9627a402620453610b3e6923f879fd84",
>     "981ade6e73ff9ce420aa29143039de0aaccb9770"
>   ],
>   "returncode": 0,
>   "stdout": "M\u0000CHANGES.rst\u0000M\u0000docs/serializer.rst\u0000M\u0000src/itsdangerous/__init__.py\u0000M\u0000src/itsdangerous/_json.py\u0000M\u0000src/itsdangerous/jws.py\u0000M\u0000src/itsdangerous/serializer.py\u0000"
> }
