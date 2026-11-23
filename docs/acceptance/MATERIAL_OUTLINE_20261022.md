# Materials 章节与 Topic 提案验收

日期：2026-10-22。依据 PROJECT_TECHNICAL_INTERVIEW_GUIDE.md 的 chapter splitting、上传后 Topic proposals 与 Accept / Reject，以及 HANDOFF.md 上轮下一阶段入口。

## 交付范围

依据已解析 heading 块及已有 headingLevel/text_level/Word 样式/MinerU 层级数据构建逻辑章节。所有内容块按 sequence_index/id 排序后进入连续章节，前言保留但不生成 Topic；每个标题形成一个提案，包含原文标题、层级路径、页码和块成员。没有标题时保留正文并明确提示没有提案，不从正文猜测知识点。

新表 material_outlines 保存 canonical 来源快照及章节，material_topic_proposals 保存人工决定、版本和稳定 Topic ID。存储和确认都核对本人同科目来源，SQL 检查全部块的有序分区。快照涵盖块 ID、类型、原文、顺序、页码、metadata、structured_data；正文变化同样使旧批次失效。确认锁定资料、提案和已有来源块，在事务内重查快照与版本。

重复生成复用同快照批次，保留拒绝/接受结果；来源恢复时可重新选中旧批次。同一决定重放不创建新 Topic，反向决定冲突。用户可修正接受名称；新 Topic 引用原文标题并归入对应章节 Unit，已有同名/别名 Topic 保持既有分组和用户元数据，归档 Topic 不复活。不写覆盖记录、不提升掌握度。

主异步资料 Worker 完成后尝试准备提案，失败不改变可检索资料的成功状态。旧资料、旧同步上传和失败的可选后处理可从资料页手动补齐。纯规则处理，没有新增模型调用。

API：

- `GET /materials/{material_id}/outline?subject_id=…`：读取最近准备的批次，返回 stale 状态。
- `POST /materials/{material_id}/outline?subject_id=…`：生成/复用批次。
- `POST /materials/topic-proposals/{proposal_id}/decision`：version、action=accept/reject、可选 title。

服务端显式分页读取最多 2001 块以检测上限；最多接受 2000 块、60 节、4 MB 快照。超限明确拒绝，不静默截断。新表认证用户只有本人读取权限，变更 RPC 仅 service_role 可执行；纳入隐私导出，随资料/科目删除级联。已经接受的课程 Topic 保留，引用中的资料可能随后不可用。

## 验证证据

| 验证 | 结果 |
|---|---|
| 新增 `test_material_outline.py` | 25 项回归 |
| 完整后端 pytest | 567 passed, 3 warnings（既有依赖弃用提示） |
| Ruff F / 离线 quality gate | 通过 |
| 前端 lint / build | 通过，最大 chunk 255.64 kB |
| Materials 页面及新组件静态 UI 检查 | 零提示 |
| 本地 PostgreSQL 047 | 已安装；fixture 全部回滚 |
| 实际 Supabase 只读 outline API | 200；跨科目 404、匿名 401，认证为测试覆盖 |

单元与 API 回归覆盖前言/层级标题/完整成员顺序、多种层级元数据、无标题行为、2000 块/60 节/标题长度/快照体积边界、超过 1000 块的分页读取、未入库拒绝、参数校验、数据库错误映射、用户/科目参数传递、隐私表登记，以及可选章节步骤成功/失败都保留 Worker 主任务成功。

真实 SQL 验收覆盖伪造快照与不完整分区拒绝、同快照复用、无自动 Topic 创建、CAS、相同决定重放、反向决定拒绝、Unit/别名复用、编辑名称、拒绝保留、正文变化 stale、恢复旧快照、归档 Topic 原子回滚、无 topic_coverage 写入、只读 RLS/私有 RPC 及删除资料级联。没有写实际用户学习数据或调用真实模型。

复跑：

```powershell
cd C:\Users\xingk\Desktop\Final-Term-main\backend
.\.venv\Scripts\python.exe scripts/verify_material_outline.py --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次安装或刷新本模块函数使用 `--apply --api`，脚本拒绝非本地数据库；其他环境按迁移流程安装 047。沙箱连接本机 5432 超时后，验收在获批的本机连接权限下完成。本次没有重启已有 API/Worker，没有修改实际 `.env` 或用户技术指南。

## 保留边界

- 这是逻辑章节划分，不生成拆分文件、不改变原文或已有检索索引；没有用户调整深度/拖拽边界、通用 syllabus 语义解析或从正文提炼 Topic。
- 标题质量取决于现有 parser；目录、重复页标题和不准确层级可能成为提案，需要人工拒绝/修正。没有执行指南要求的 30 页复杂课件抽样，不能宣称真实解析质量达标。
- 原文标题和页码可核对，但没有新增完整原文预览器。已有章节快照随来源变化失效，跨服务重解析/新增块并发与长期快照保留策略仍需专门验收。
- 当前同名章节复用、同名/别名 Topic 复用；同名但语义不同的内容需用户改名，未新增自动语义合并。
- 静态检查不替代真实浏览器。当前没有可调用浏览器工具，键盘/窄屏/JWT/持续 Worker/真实模型 E2E 未验收；主异步 Worker 的可选后处理以代码与模拟依赖回归验证。
- 下一阶段：上传后自动 Notes，复用统一转换的幂等任务/原子发布。material outbox/claim、完整阶段 checkpoint、取消恢复及上一阶段音频工具/真实 ASR 仍保留待办。
