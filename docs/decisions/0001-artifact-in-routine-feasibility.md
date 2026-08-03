# 决策 0001:云端 schedule routine 能否直接调用 Artifact 工具

**探针时间：** 2026-08-03T09:09Z ~ 2026-08-03T09:15Z
**探针 Artifact URL：** https://claude.ai/code/artifact/c57d0bce-698c-48fe-9109-9b7f82b183b0
**探针 routine trigger_id：** trig_01FHBJuVXjFYvaDoEhuBv1Tr

## 过程记录

1. 最初尝试用 `general-purpose` 子代理执行整个探针任务(发布 Artifact → 创建 RemoteTrigger routine → 等待 → 检查)。子代理成功发布了探针 Artifact(步骤1-2),但在步骤4卡住:多次尝试 `ToolSearch(query="select:RemoteTrigger")` 及其他关键词变体,均返回 `No matching deferred tools found`。即使先加载了 `schedule` skill 也没有改变结果。**结论:`RemoteTrigger` 工具在 Agent 工具派生的子代理会话里不可用,即使系统提示文本列出了它的名字。** 这是本次探针过程中的第一个重要发现,已导致后续步骤改由主对话(本会话)直接执行。
2. 主对话确认 `/tmp/lit-radar-probe/placeholder.html` 文件在文件系统中可见(子代理与主对话共享同一台机器的 /tmp),探针 Artifact 也已存在且未被修改,于是复用同一个 PROBE_URL,不重新发布。
3. 主对话直接调用 `RemoteTrigger`(该工具在主对话里可以正常加载和调用)创建了一次性 routine:`run_once_at=2026-08-03T09:14:15Z`,`allowed_tools=["Bash","Write","Artifact"]`,`sources=[]`。
4. 等待到触发时间之后。

## 证据

- **WebFetch 检查探针页面内容(09:15:57Z 左右)：** 页面正文仍是 `<p>PROBE_MARKER: v0-not-yet-updated</p>`,**没有变成** 预期的 `v1-updated-by-cloud-routine-at-...`。
- **RemoteTrigger get 响应：** `"ended_reason":"run_once_fired"`,`"last_fired_at":"2026-08-03T09:14:22.647650Z"`——证实 routine 确实按计划触发并执行完毕(不是没跑,也不是还在排队),但探针页面内容没有任何变化。
- 尝试通过 `WebFetch` 查看 `https://claude.ai/code/routines/trig_01FHBJuVXjFYvaDoEhuBv1Tr` 页面获取该次运行的详细日志/报错信息,返回 `HTTP 403 Forbidden`(该页面不在 WebFetch 可用 claude.ai 登录态豁免范围内,只有 `/code/artifact/{uuid}` 是例外)。因此**无法拿到云端 routine 会话内部的具体报错文本**,只能依据"routine 确认执行完毕 + 探针页面确认未被更新"这一组合结果做判断。

## 结论

**FAIL**(观测层面确定,根因层面不完全确定)。

- 确定的事实:routine 真实触发并执行完成(`run_once_fired`),但探针 Artifact 在触发后没有被重新发布/更新。
- 不确定的细节:由于无法读取云端 CCR 会话内部日志,不能 100% 区分是"Artifact 工具在 CCR 环境里根本不可用/不在 allowed_tools 生效范围内",还是"Artifact 工具调用了但因为其他原因报错"(比如 url 参数处理、跨会话所有权校验等)。但无论具体原因是什么,**这条路径在真实测试中没有产生预期效果**,不能作为生产架构的基础。
- 与探针过程记录第1点合并看:`RemoteTrigger` 本身在 Agent 子代理里都拿不到,进一步佐证"深层工具(Artifact/RemoteTrigger 这类较新的运行时能力)在非主会话的执行环境里可用性有限"这一模式,和 CCR 云端 routine 会话调不通 Artifact 工具是同一类限制的两个观测实例,而不是孤立的偶然故障。

## 后续架构选择

采用实现计划任务 7 的 **路径 B(半自动)**:

- 生产 routine 每日只负责跑 `inject.py` 渲染最新 `dist/dashboard.html` 并 commit/push 回仓库,不尝试调用 Artifact 工具。
- 本机通过 `/loop` 定期(建议与云端 routine 错开 10 分钟以上)拉取仓库最新 `dist/dashboard.html`,调用 Artifact 工具重新发布。
- 这意味着"全自动、完全无人值守"的目标在当前工具能力下无法 100% 达成——半自动路径依赖本机保留一个可运行 `/loop` 的 Claude Code 会话。这一限制已在设计规格第 8 节预先写明,不是新增的意外妥协。
