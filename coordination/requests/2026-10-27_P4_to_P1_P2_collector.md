# P4 → P1/P2：项目历史采集器基础数据接口接收

日期：2026-10-27｜规划/契约1.4.0｜状态：待接收方实际验收。

P4已完成固定relore源码移植、适配与基础数据接口。安装、参数、结果及示例见
[采集器说明](../../docs/collector.md)，真实验证及独立复核见[P4交接](../../deliveries/P4/2026-10-27/handoff.md)。

- P1：复用collect_repo/index_threads/replay_capture，接入正式profile、C5来源映射和唯一pipeline；保持原来源、捕获完整性与请求预算信息。
- P2：复用search_history及本地索引，接入正式QueryResult与C8共同来源池；本接口当前检索讨论，发布/代码/提交等补充来源仍由所属模块完成同源适配。
- 接收方核对提交/接口版本后，运行doctor和最小入库/检索或冻结回放，把实际接收结果写本人已有handoff并引用本交接。P4继续维护该模块并处理反馈。

collector_v1不是正式BuildJob/QueryResult；capture中的原始来源标识也不是C5统一ID。
原文输入与运行结果可用，正式格式映射和全系统验收继续按契约完成。当前不声称P1/P2已接收。
