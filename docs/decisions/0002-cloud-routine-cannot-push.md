# 决策 0002:云端 schedule routine 无法推送代码到仓库,路径B进一步降级为"本机 /loop 全权处理渲染+发布"

**时间：** 2026-08-04

## 背景

决策 0001 已确认云端 routine 无法直接调用 Artifact 工具(探针 FAIL),因此采用路径B:云端 routine 只负责"拉数据→跑inject.py→渲染→commit+push回仓库",本机再拉取渲染结果发布 Artifact。

本次尝试落地路径B第一步(`lit-radar-daily-render` routine)时:

1. 首次创建 routine 时报错 `authentication_error`:"Connect your GitHub account before saving a routine that uses a GitHub repository"——说明 claude.ai 账号此前未连接 GitHub,已引导用户在 https://claude.ai/customize/connectors 完成连接。
2. 连接后重试,又报 `environment_not_found`(旧的 `env_01N5xPtBtmw6Mgtv21ctQhhc` 失效)。重新查询 `schedule` 技能拿到新环境 `env_01Qc7HdWd7WFPjBcC5e1r53z`(账号连接GitHub后被自动新建),用新环境ID成功创建了 `lit-radar-daily-render` routine(`trig_01GUzMCaCR2vi3ehtQZxmkMU`)。
3. 手动 `run` 触发该 routine,`RemoteTrigger get` 显示确实 fire 了(`last_fired_at` 有值),但等待5分钟后检查仓库(`gh api .../commits/main`、`gh api .../events`),**没有任何新的 push/commit**——渲染结果没有被推回仓库。
4. 为排除"是不是我的渲染prompt本身有bug"这个变量,额外创建了一个更简单的**专门诊断routine**(`lit-radar-diag-push-test`),唯一任务是:切到新分支 `diag-test`、写一个诊断文件、commit、`git push origin diag-test`(不碰main,不force push)。这个诊断routine同样确认 `ended_reason: run_once_fired`(真的跑完了),但等待后检查 `gh api .../branches`,**远程仓库里根本没有出现 `diag-test` 这个分支**——证明连最基础的、往非main分支推送一个诊断commit这种最小操作都没有发生。
5. 无法通过任何现有工具查看云端routine会话的实际执行日志/报错(`https://claude.ai/code/routines/{id}` 页面用 WebFetch 访问返回 `403 Forbidden`,不在 WebFetch 的 claude.ai 认证豁免范围内;`RemoteTrigger get` 只返回routine配置和触发时间戳,不含会话transcript)。

## 结论

**两次独立、方法不同的真实测试(生产渲染routine + 专门诊断routine)得到一致的负面结果:当前账号下的云端 CCR routine 会话对这个 GitHub 仓库没有实际推送权限**,即使:
- claude.ai 账号已连接 GitHub(否则连 routine 都创建不了)
- routine 的 `session_context.sources` 里正确配置了 `git_repository` 指向该仓库
- routine 确认真实触发并执行完毕(`ended_reason: run_once_fired`,不是没跑或还在排队)

具体根因无法进一步确认(可能是 GitHub App 连接时只授予了读权限/未对该仓库开启写入范围,也可能是 CCR 的 `git_repository` source 本身设计上就是只读集成,不支持 `git push`)——由于看不到会话日志,不作进一步猜测性归因。

## 后续架构调整

放弃"云端routine渲染+推送"这一环节。最终架构简化为:

- **GitHub Actions**(已验证跑通,见 `.github/workflows/fetch.yml` 和 run `30883842631`/`30884544298`):每日06:00 UTC 抓取数据、commit、push 到仓库——这一环完全在GitHub自己的基础设施内完成,不涉及claude.ai routine,权限模型不同,不受本决策影响,继续保留。
- **本机 `/loop`**(新增,替代原计划里云端routine+本机手动/半自动的组合):每日从公开仓库拉取最新 `data/data.json`(公开仓库,HTTPS只读克隆/fetch不需要任何认证)→本地跑 `python3 scripts/inject.py` 渲染→调用 `Artifact` 工具以 `config/artifact_url.txt` 记录的URL重新发布。

**代价**:这不是"云端全自动、本机可以完全不用管"的架构,而是需要本机保留一个运行着 `/loop` 的 Claude Code 会话才能完成"渲染+发布"这一步。这一限制在设计规格第8节就已经预见并写明是路径B的已知代价,只是没想到路径B自己的"云端routine推送"这一子环节也会失败,导致本机 `/loop` 需要覆盖的范围从"只做发布"扩大到"数据拉取之后的全部本地环节(渲染+发布)"。

## 已创建但确认不可用的云端routine(保留但已禁用,不建议删除以备后续排查)

- `trig_01GUzMCaCR2vi3ehtQZxmkMU`(`lit-radar-daily-render`):已通过 `RemoteTrigger update` 设置 `enabled: false`。
- `trig_01DfxLPKahkfqHW7yRephjmw`(`lit-radar-diag-push-test`):一次性routine,`run_once_fired`后已自动禁用。
- 更早的探针routine `trig_01FHBJuVXjFYvaDoEhuBv1Tr`(决策0001所用):同样早已 `run_once_fired` 自动禁用。

如果未来 claude.ai 平台对 CCR routine 的仓库写权限模型有变化,可以参考本决策文档里记录的诊断方法(专门diag routine + 检查独立分支是否出现)重新验证,不需要每次都用完整的生产prompt去试错。
