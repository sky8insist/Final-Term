# Materials 用途与失败恢复验收

日期：2026-10-19。依据用户技术指南 Materials / Ingestion 待办及 HANDOFF.md 上一阶段入口。本轮只覆盖用途、失败阶段展示和重试，不表示 Materials 全模块完成。

## 实现

- `materialPurpose`：learning / syllabus / reference；两种上传接口均使用枚举表单参数校验并持久化，历史资料迁移默认 learning。选择 syllabus 不直接触发考试创建，资料页链接既有日历候选流程。
- `GET /materials/processing?subject_id=…`：先核对科目归属，私有 SQL RPC 对每份资料取最新 material_ingestion 任务，输出经既有任务模型序列化的数据及 sourceAvailable。不通过公共任务列表的 100 条上限推测资料失败状态。
- 来源可用性是原文件资产记录和 expires_at 的判断；对象可能已在外部丢失，此时 Worker 下载失败会进入有上限的错误处理。
- failed ingestion 手动重试锁定任务/资料并检查原文件记录、归属、任务类型、资料状态和其他活动 ingestion。开始新的有限自动重试周期；previousAttempts/manualRetryCount 记录历史，MinerU 批次不丢弃。其他任务类型保持既有重试规则。
- broker 投递失败使用私有 RPC 将仍 queued 的任务及 queued 资料标为 failed，错误文本不暴露 broker 地址。运行中的任务保持运行。重新投递也采用相同处理；这里依赖用户手动重试，没有新增自动 outbox。
- 资料 Worker 的源文件查找和下载纳入异常处理；失败元数据保留 source / queued / parsing / embedding / indexing，终止时同步资料失败。失败处理发现已取消则保留取消状态。
- 去重提前到新增上传配额检查之前；不同用途的重复文件返回 409，原分类不被覆盖。新对象路径包含资料 ID，失败后重新上传使用独立路径。失败资料仍不参与成功去重，重新上传仍消耗正常配额。
- 资料页面补充用途选择/展示、失败错误、自动尝试进度、重试按钮与源文件失效提示；科目切换以 key 重建，迟到的加载结果通过请求序号丢弃；支持键盘文件选择、窄屏纵向排列和长文件名。

## 验证证据

| 检查 | 结果 |
|---|---|
| 新增 `tests/test_material_recovery.py` | 21 passed |
| 完整后端 pytest | 542 passed, 3 warnings（现有依赖弃用提示） |
| Ruff F | 通过 |
| 统一离线 quality gate | 通过；不代替真实模型质量评测 |
| 前端 TypeScript lint / Vite build | 通过；最大 chunk 255.23 kB |
| Materials 静态 UI 检测 | 零提示 |
| Lectures 静态检测 | 现有一条互斥 class 配色提示；本轮只更新重试按钮的显示条件 |
| 本地 PostgreSQL 046 | 已安装，验证记录回滚 |
| 本地 Supabase 只读 API | materials / processing 200、跨用户科目 404、匿名 401；测试认证覆盖 |

数据库验收脚本 `backend/scripts/verify_ingestion.py` 覆盖用途默认及约束、资料/任务汇总归属、缺失/过期原文件拒绝、自动尝试耗尽后人工新周期、保留 MinerU 元数据、重复重试冲突、queued 投递失败、running 状态保护、成功重复文件冲突的整笔回滚、RLS 及 RPC 仅 service_role 可执行。所有 fixture 数据在事务后回滚，不写实际用户学习数据。

复跑命令：

```powershell
cd C:\Users\xingk\Desktop\Final-Term-main\backend
.\.venv\Scripts\python.exe scripts/verify_ingestion.py --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次缺少 046 可使用 `verify_ingestion.py --apply --api`；脚本限制本地数据库，`--apply` 只安装缺失的本轮迁移，不刷新已存在实现。其他环境按正常迁移流程安装 046，并部署 API、前端及 Worker。本次没有重启既有服务。

## 保留待办与边界

1. 下一阶段：章节拆分、来源证据/版本校验的 Topic proposals 及 Accept / Reject；随后接上传后自动 Notes。
2. 当前手动重试重新运行 pipeline，复用原有成功音频段转录和 MinerU batch；没有新增逐阶段 checkpoint，也没有自动跳过已完成 embedding/indexing。
3. DB、Storage、Celery 之间仍是多次操作；未实现 material outbox、租约 claim、重复 delivery 的完整互斥、所有取消/重试竞争的原子栅栏。持续 Worker/Beat 和外部服务故障演练未执行，不能宣称恰好处理一次。
4. 已取消任务不属于本次 failed 重试入口；旧取消状态的恢复及历史无任务记录需要后续专门处理。历史错误没有 failedStage 时页面显示一般处理失败，不伪造阶段。
5. 静态检测不是浏览器验收。当前无可调用浏览器工具，真实文件选择/键盘/手机布局、真实 JWT、真实模型/存储上传均未做 E2E。
6. 上一阶段 FFmpeg/ffprobe 缺失仍未补齐，真实音频解码和 ASR 尚未验收。实际 `.env` 和用户技术指南未改动；没有下载外部二进制。
