# 上传后自动 Notes 验收

日期：2026-10-22。依据用户技术指南 Materials / Ingestion 的上传后 Notes 和交接文档上一阶段入口。

## 交付行为

主异步上传 `/materials/uploads` 支持可选表单 `notesMode`，默认不生成笔记；可选摘要、标准、详细、考试重点四种既有模式。用户选择后，模式与稳定请求 UUID 随 materials 插入保存，资料入库成功再接入统一转换。现有同步上传接口没有增加此选项。

生成范围遵循现有 material→notes 转换：最多前 30 个内容块、count=10。上传前及结果状态均提示范围，较长资料返回 material_first_30_blocks 警告，不宣称全文覆盖。没有新增模型协议或绕过 Notes 草稿校验。

同用途已有文件可以在成功去重分支补登记 Notes 申请，不重新上传文件或消耗新增上传配额。同模式复用原申请和 UUID；不同模式冲突，其他笔记通过手动转换另建请求。省略 notesMode 保留已有申请，不代表取消任务。

## 可靠性和状态

- 主 Worker 入库后尝试准备 Notes；用户未选择时直接跳过。Notes 可选步骤异常不改变资料入库成功状态。
- 每分钟补扫最多 20 份 ready 且尚未确认入队的申请；私有 RPC 使用数据库行锁、1 分钟领取窗口和最多 3 次自动准备尝试。失败可手动重置。此窗口只保护申请准备，不是材料解析任务的完整 claim/租约方案。
- 准备调用现有 conversion.enqueue，使用相同申请 UUID、资料、模式和 count。learning_conversions 插入触发器在同一事务中标记申请已接收，不依赖后续 Python 确认才能持久化。
- 入队后的 broker 故障由已有 conversion outbox 补扫；生成沿用转换任务的领取、三次预算、来源复核、取消和原子发布。同一个申请不建立另一套生成实现。
- 取消或删除任务/笔记结果不会自动生成替代品。需要新笔记时用户通过手动转换发起新的请求。失败生成的重试仍使用同一个 conversion，并遵守既有剩余尝试预算。
- 汇总 API 一次返回资料及 Notes 的独立状态、模式、错误、警告、结果链接与能否重试。资料页轮询等待中的 Notes，提供打开笔记、查看转换任务、重试入口；尚未入队失败的手动重试可重置申请准备次数。
- `POST /materials/{id}/notes/retry?subject_id=…` 先校验本人同科目。新 RPC 只允许 service_role；新字段随现有 materials 隐私导出和删除，无新增隐私表。不写覆盖或提高掌握度。

## 证据

| 检查 | 结果 |
|---|---|
| 新增 `tests/test_upload_notes.py` | 31 项回归 |
| 完整后端 pytest | 598 passed, 3 warnings（既有依赖弃用提示） |
| Ruff F / 离线 quality gate | 通过 |
| 前端 lint / build | 通过；最大 chunk 255.79 kB |
| Materials 静态 UI 检测 / diff 检查 | 通过 |
| 本地 PostgreSQL 048 | 已安装；验收数据全部回滚 |
| 实际 Supabase 只读汇总接口 | 200，跨科目 404、匿名 401；测试认证覆盖 |

回归覆盖默认关闭/四种枚举和非法值拒绝、申请随资料插入保存、未入库/未选择/已投递跳过、稳定请求 UUID 与转换参数、领取冲突、错误记录、补扫继续处理其他资料、删除不再登记、失败重试复用转换、错误详情隔离、API 参数归属以及 Worker 可选步骤成功/失败不影响资料入库。

真实数据库回滚验收覆盖模式与 UUID 配对约束、配置归属/同模式重放/不同模式冲突、ready 门槛、1 分钟领取窗口、三次准备预算/手动重置、非法转换确认拒绝、转换插入即确认申请、请求去重、重复 finish 仅一个 Notes/历史版本、结果链接状态、删除笔记不重新登记、无 topic_coverage 写入、私有 RPC 权限与跨用户 RLS。

Notes 发布使用固定、带 canonical 引用的草稿验证；未调用真实模型、Redis broker、真实用户文件上传或持续 Worker。没有可调用浏览器工具，静态检查不能替代浏览器键盘/窄屏/JWT E2E。

复跑：

```powershell
cd C:\Users\xingk\Desktop\Final-Term-main\backend
.\.venv\Scripts\python.exe scripts/verify_upload_notes.py --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次安装或刷新本模块函数可加 `--apply`；脚本拒绝非本地数据库。其他环境需先具备 043 统一转换及 046 资料处理汇总等历史依赖，再安装 048，部署前后端并重启 Worker/Beat 以加载新增补扫任务。本次没有重启既有服务、修改实际 `.env` 或用户技术指南。

## 后续范围

Materials 三阶段的首轮增量已接通，下一阶段按指南推进 MinerU / Parse 的标题层级、图表 caption、公式上下文和解析置信度。

全资料分批 Notes、按章节选择生成范围、章节边界/深度编辑、通用 syllabus 语义解析仍待补。当前最多前 30 块的既有来源范围不能视为长资料的完整笔记。材料摄取完整 outbox/claim/checkpoint、取消恢复以及真实 ASR/模型/浏览器/JWT/持续 Worker 链路保留待办。
