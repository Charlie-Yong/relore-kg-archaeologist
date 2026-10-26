# 本机能力检查

由各角色AI在首次实际任务中检测并保存Pn.json，成员无需填表；没有检查则null。首次真实提交/PR顺便验证能力，不另造空提交或演练PR。此处只提供格式，没有预填任何成员已通过。

~~~json
{
  "role": "P1",
  "os": null,
  "can_read": null,
  "can_write": null,
  "can_run": null,
  "can_network": null,
  "python": null,
  "git": null,
  "shell": null,
  "git_push": null,
  "github_pr": null,
  "github_merge": null,
  "github_token_read": null,
  "graph_access": null,
  "model_access": null,
  "checked_at": null
}
~~~

shell记实际命令通道；git_push、github_pr、github_merge分别以真实推送、PR或实际授权/操作核验为依据，不能从公开可读推定可写。github_token_read只由需要采集的角色记录只读令牌访问结果，不存令牌；其他人保持null并在已有交接说明无需该项。Git写权限与采集只读令牌分开，不要求六人申请全部权限。字符串字段可记录检测到的版本，能力布尔值填true/false/null。model_access仅记服务/实际模型与连通状态，不存key；图访问可为本人无需数据库。P1/P2与演示机检查完整服务，P4配合macOS最小验证，其他人不必先部署全栈。

网络受限时先区分本机限制、代理与服务错误，不能只凭一条“token invalid”推断账号失效。AI先利用现有通道排查依赖、代理、权限和配置，记录真实错误与可继续工作；仅确需本人账号/设备动作才请求最小接管。只读会话先准备补丁/命令，一次请求可执行通道，不默认要求成员逐条代跑。
