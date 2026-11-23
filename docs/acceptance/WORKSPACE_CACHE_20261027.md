# Workspace Cache v2 验收 — 2026-10-27

本轮完成指南第 23 节的版本化快照与同步失效首轮，重点阻止评分完成后回退到旧学习状态。缓存始终是展示快照，不作为评分、Mastery、计划发布或权限的权威来源。

## 实现

- 054 建立本人/资源/科目（或全局）版本表；canonical 写入及领域事件插入在同事务推进 revision，避免 30 秒队列延迟。Mastery/评分同步失效 Dashboard/Plan/推荐，资料入库失效导图；无关聊天和其他科目保持原 dataVersion。projectionVersion 仅供诊断，版本有效性不依赖 Worker 完成。
- version RPC 校验资源契约与本人科目；认证只读、服务角色调用。token 绑定 schema/rule/用户/资源/科目/revision，学习类资源带上海分钟桶。dataVersion 不带分钟桶，轮询不会因时间自然推进而误报数据写入；fallback 本身过分钟边界会提示过期。
- Redis 使用 v2 用户/资源/科目/版本键，旧 writer 不能覆盖新键。PUT expectedVersion 不匹配为 409；GET 在 Redis 前后核验，旧版/坏 envelope/错科目/版本变化返回 miss。DB 版本不可验证时拒绝 fallback。成功缓存接口 no-store；v1 不迁移、不加载，按 TTL 淘汰。
- 主读取前后版本不同最多重取一次，持续变化拒绝。主接口成功不因 cache 故障失败；无法校验不缓存。临时失败仅接受验证过的 v2 fallback，权限/不存在/验证/冲突错误不回退。账户切换丢弃旧响应，Outlet 按账号重挂载。
- 缓存横幅按资源/科目/账号隔离，无关成功请求不清除别处警告。当前支持页面在可见时每 15 秒/获焦/恢复可见校验数据版本，显示缓存、未复核、更新/过期与显式刷新按钮；不自动重载正在填写的表单或答题。
- 清空数据在 DB 原子撤销旧代次后清理本人的 Redis 命名空间。即使 Redis 不可用，旧版本仍不可读；物理残留等 TTL。清除后全局失效标识为不含学习内容的撤销元数据，账户删除时级联。科目删除后的读先验证归属。

## 验证结果

| 检查 | 结果 |
|---|---|
| 新增后端回归 | 20 passed |
| 完整后端 pytest | 805 passed，3 项既有依赖弃用警告 |
| 前端 Node 缓存回归 | 19 passed |
| Ruff F / 统一 quality gate / diff | 通过 |
| 前端 lint/build | 通过，最大 chunk 254.38 kB |
| 本地 PostgreSQL / Redis / Supabase / 双 DB 会话 | 通过 |

后端单测验证旧版本读写、Redis 读取中途发生变化、损坏/旧 envelope、验证不可用不读 Redis、不同版本键隔离、接口身份/错误/参数、非有限 JSON 拒绝、隐私 DB 撤销优先于 Redis 清理。既有三项缓存测试升级到 v2；隐私测试增加缓存撤销断言。

Node 单测直接运行实际 TypeScript helper 的转译结果，覆盖主请求成功/版本服务故障/Redis 写失败、验证过的 fallback、401/403/404/409/422 不回退、旧 schema/版本拒绝、读取中途变化重取一次/持续变化冲突、账户中途切换与跨资源/科目提示隔离。首次 Node 子进程被沙箱 EPERM 阻止后，按批准的测试命令执行通过。

## 真实跨连接验收

`verify_workspace_versions.py` 使用实际本地 Redis 和 Supabase RPC/API。独立 writer 连接提交评分与 Mastery，从另一连接/服务读取当前版本：

- 提交事务内已改变版本，不需要等待 Worker。
- 旧合成 .2 快照不可读取、旧 PUT 为 409；当前合成 .9 快照保存/读取通过。
- 原科目 Plan/推荐变化，无关聊天/其他科目/其他用户 dataVersion 保持不变。
- 资料 ready 推进 Mind Map 版本；外人科目 404、无 scope/错误全局 scope 422、匿名 401、no-store 和私有 RPC/RLS 通过。
- 正常清理删除 Redis 键；模拟 Redis 不可用后，恢复连接也无法读出撤销前科目快照。

为跨连接可见而提交的临时用户/数据在 finally 中按精确生成 ID 清理；精确 Redis 测试键也已删除。未写真实用户数据、未调用模型或付费服务。API 身份采用依赖覆盖，未声明真实 JWT 或浏览器 E2E。

## 复跑与部署

```powershell
# backend
.\.venv\Scripts\python.exe scripts/verify_workspace_versions.py
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
# frontend
node --test tests/versionedCache.test.mjs
npm run lint
npm run build
```

仅本地首次安装/刷新 054 使用 `--apply`。脚本拒绝远端 DB/Supabase/Redis，并会创建后清理临时用户。其他环境先安装历史依赖与 054，再部署 API/前端；无需新 Beat/Worker 任务。旧客户端 PUT 没有 expectedVersion 会被拒绝，部署需同步前端，旧 v1 键不会恢复使用。本次未改实际 `.env`、用户指南或重启既有服务。

## 边界

当前不是 WebSocket 推送，也不把轮询等同真正浏览器多端同步验收。当前页仅提示刷新；对现有答题/表单不强制重载。Learner State、推荐、实时导图等既有权威读取继续绕过快照。DB/网络不健康时宁可拒绝缓存，不能提供全离线工作台保证。

旧多版本键按 TTL 保留，未新增总体容量淘汰/P95 基准；单快照仍最多 1 MB。新提示静态检查仅保留既有退出按钮互斥 hover 的提示，新增横幅代码已核对。无可调用浏览器工具，真实浏览器/键盘、网络恢复、多设备与广泛并发验收仍待补。下一阶段为产品可观测性与质量审计。
