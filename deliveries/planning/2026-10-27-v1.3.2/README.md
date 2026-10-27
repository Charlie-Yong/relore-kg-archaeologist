# v1.3.2 Release身份与代码样本单位修正

2026-10-27｜规划v1.3.2 / 契约1.3.2。用户授权修改复核确认的两处问题；本次交付为规划修订。

## 修改与接收

1. Release按规范repo与原样tag生成身份，commit_sha保留为属性；不同tag即使指向同一提交也不合并。P1实现公共ID、P3生产记录、P2导入校验，P5/P6消费。接入旧原型时重建相关端点和映射，具体迁移边界见[变更记录](../../../03_范围与契约变更记录.md)。
2. 代码实验统一为12个单文件快照，每个(repo,path,commit_sha)组合计一个样本，4开发/8测试。前后比较复用已采快照、明确配对并保持主题隔离；P6工作单与总规划同步该口径。

默认采样规则按已有试跑与冻结流程验证，配额、题量和日期不变。六份公共契约完整同步；历史交付与试跑原档保留。正式模块仍为todo，本次没有修改原型代码、执行模型请求或运行课程实验，也没有提交或推送远端。

## 检查记录

[planning_checks.json](planning_checks.json)保存当前契约、六份工作单哈希、链接和状态检查结果；检查仅覆盖规划资料。

实际结果：六份公共段、版本及哈希一致，83个本地链接和六角色状态检查通过；现有7项检查工具回归全部通过，退出码0；git diff --check无错误。检查工具未修改，角色仍为todo。

~~~text
python3 tools/sync_workorders.py
python3 tools/check_planning.py --report deliveries/planning/2026-10-27-v1.3.2/planning_checks.json
python3 -m unittest discover -s tools -p 'test_*.py'
git diff --check
~~~
