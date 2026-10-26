# 本机能力检查

每位角色首次实施后保存Pn.json，逐项检测并填写；没有检查则null。此处只提供格式，没有预填任何成员已通过。

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
  "graph_access": null,
  "model_access": null,
  "checked_at": null
}
~~~

字符串字段可记录检测到的版本，能力布尔值填true/false/null。model_access仅记服务/实际模型与连通状态，不存key；图访问可为本人无需数据库。P1/P2与演示机检查完整服务，P4配合macOS最小验证，其他人不必先部署全栈。

网络受限时先区分本机限制、代理与服务错误，不能只凭一条“token invalid”推断账号失效。AI先利用现有通道排查依赖、代理、权限和配置，记录真实错误与可继续工作；仅确需本人账号/设备动作才请求最小接管。只读会话先准备补丁/命令，一次请求可执行通道，不默认要求成员逐条代跑。
