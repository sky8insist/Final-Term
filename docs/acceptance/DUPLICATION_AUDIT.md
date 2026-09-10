# 代码去重与失效代码审计

审计日期：2026-08-24

## 工具与口径

- Ruff 0.16.4：首次全规则扫描 214 条；清理后以 `--select F` 验证未使用 import 和未定义名，结果 0 条。
- Vulture 2.16：首次 60% 扫描用于候选发现；清理后 80% 扫描只剩 Pydantic validator 的两个 `cls` 误报。
- Knip 6.32.2：首次发现 2 个未使用依赖和 11 个未使用导出；清理后 0 条。
- jscpd 5.0.16：Python/TypeScript/TSX/CSS，阈值 5 行/40 tokens。

## jscpd 前后对比

| 指标 | 清理前 | 清理后 | 变化 |
| --- | ---: | ---: | ---: |
| 扫描文件 | 119 | 114 | -5 |
| 克隆块 | 19 | 14 | -5 |
| 重复行 | 133 | 91 | -42 |
| 总重复行率 | 1.01% | 0.71% | -0.30 pp |
| 重复 token | 1,138 | 880 | -258 |
| 总重复 token 率 | 0.97% | 0.77% | -0.20 pp |

## 已处理候选

| 候选 | 调用方核实 | 处理 | 回归证据 |
| --- | --- | --- | --- |
| 无前缀与 `/api/v1` 双挂载 | 前端与维护脚本可统一到 v1；旧测试仍引用无前缀 | 删除无前缀挂载，更新测试/脚本 | OpenAPI 契约测试 + 全测 |
| `/exams/attempts/*` 与 `/exam-attempts/*` | 前端和验收脚本使用后者 | 删除前者 4 条 | `test_removed_compatibility_routes_stay_removed` |
| 考试同步/异步 HTTP 生成 | 前端使用 `/exams/generations` | 删除 `POST /exams`；保留 Worker service | 考试生成测试 + OpenAPI 契约 |
| 计划同步/异步 HTTP 生成 | 前端使用 `/study-plans/generations` | 删除 `POST /study-plans`；保留 preview 与 Worker service | 计划测试 + OpenAPI 契约 |
| outline 与 artifacts outline | 前端使用 `/artifacts/*` | 删除 `api/outline.py` | OpenAPI 契约 |
| quiz 与 exams | 前端使用 exams | 删除 `api/quiz.py` | OpenAPI 契约 |
| 两个 generation service 指纹/幂等/建任务 | 两者逻辑等价，仅 task type/result key 不同 | 抽取 `generation_task_service.py`，保留薄适配器 | 指纹稳定性测试 + 生成测试 |
| Workbench Mock | 正式前端没有调用；仅占位测试和文档 | 删除路由、121 行占位数据、测试和环境分支 | OpenAPI 不含 `/api/workbench` |
| 错题本公开功能残留 | 仅旧重定向、README 与静态脚本；无正式 API | 删除重定向/说明/静态脚本，改为“练习表现分析” | 全仓引用扫描 |
| 未使用 GSAP | 无 import | 从 package/lock 删除 | Knip 0 条、lint/build |
| 旧 agent/utility 包装 | 无生产调用；部分仅被 Vulture 命中 | 删除 4 agent、constants、eval/logger、同步 LLM 和 parse 包装 | 全测 + Ruff F |

## 保留项与理由

- `wrong_answers` 表：按要求保留历史数据结构；仍受 RLS、隐私导出和删除流程覆盖，不作为公开产品入口。
- router agent 中“错题”等关键词：用于把用户旧表达映射为“分析练习表现”，不是错题本功能入口。
- `mock_external_service.py`：自动化测试的确定性外部模型替身，与已删除的无认证 Workbench Mock 不同；真实验收必须关闭 `MOCK_EXTERNAL_APIS`。
- `/api/v1/materials/upload`：同步处理测试仍覆盖它；正式前端/E2E 已使用异步 `/uploads`。后续删除前需把同步处理链路测试下沉到 service 层。
- jscpd 剩余 14 个克隆：多数是短 API 适配/模型字段或 assistant 分支结构。继续抽取会降低局部可读性，且不属于点名的跨 service 重复；列为候选而非强制删除。

## 删除规模

变更统计在生成报告时约为 42 个已跟踪文件，78 行新增、614 行删除，另新增公共 generation service 和验收文档。最终数字以 `git diff --stat` 为准。

## 结论

点名的路由、同步/异步入口、outline/quiz、generation service、错题本残留和 Workbench Mock 已完成收敛。清理后前端死依赖/导出为零，Python 未使用 import 为零，重复行率下降到 0.71%，并由完整后端回归与前端门禁保护。
