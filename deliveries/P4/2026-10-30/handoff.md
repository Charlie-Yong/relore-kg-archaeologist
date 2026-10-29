# P4 共享模型与结构化抽取交接

日期：2026-10-30，契约1.4.1，分支feat/p4。本轮新增实现由P4角色AI完成；P4前期独立调研、方案、原型、移植及基础接口的成员贡献继续引用[原记录](../2026-10-27/handoff.md)。

## 讲解与边界

主代理在本轮先向成员发送了C0完整项目原理说明；P4角色AI完整读取工作单、AGENTS、STATUS、既有handoff、试跑记录及collector文档后，实施前向主代理发送了具体输入、处理、输出说明，由主代理负责面向成员协调。这是实际发送方式，不冒称P4直接向成员发送或成员已确认理解。

P4接收P1冻结的sources/source_units与P1/P3自动生成的subjects；模型生成候选后，程序校验同repo现有主体、项目归属、理由字段及Unicode码点引文，外库和无法映射候选留账。回答器消费P2最终上下文，只返回claims和证据。P1拥有唯一build流水线，P2拥有QueryResult，P6私有参考不进入生产开发。

## 首批：采集器接入及续作

已接收公共首批e0f4ab2，普通merge feat/p1。collector增加selected、resume_capture、initial_requests、initial_http_responses、profile_version，详见[接口说明](../../../docs/collector.md)。底层复用完整线程和成功分页，保留Link及冻结请求计数，不把回放计作新请求。

实际验证：使用主仓库既有Python3.11环境，显式`PYTHONPATH=vendor/relore:.`使import指向本副本的vendor。doctor返回bundled=true。38项当前P4测试通过（其中collector含SQLite和PostgreSQL两后端），命令：

~~~text
PYTHONPATH=vendor/relore:. RELORE_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:16432/historykg_course_test <venv-python> -m pytest tests/test_llm.py tests/test_extract.py tests/test_collector.py -q
# 38 passed in 1.62s；尚未代表P1接收验收或整系统完成。
~~~

后续批次持续更新本记录；正式实验与URL自动闭环待接收方实际运行。
