# 阶段 1–3 实施与基线报告

生成日期：2026-08-24（Asia/Shanghai）

## 本轮范围

本轮仅执行原规划中的第一阶段（建立基线）、第二阶段（代码去重）、第三阶段（接口矩阵）和第九阶段（项目面试文档）。真实外部服务 E2E、可观测性改造、性能成本采集、故障注入和第二轮真实验收不在本轮范围内，不能据此宣称真实验收完成。

## Git 与运行环境基线

| 项目 | 实测值 |
| --- | --- |
| 分支 | `main` |
| 基线提交 | `2a058b8d511f3d58bf204798d95a747eda8f269a` |
| 基线提交时间 | `2026-08-23T22:54:10+08:00` |
| 基线工作树 | clean |
| Python | 3.13.12 |
| Node.js / npm | 22.15.1 / 10.9.2 |
| FastAPI / Pydantic | 0.139.2 / 2.13.4 |
| Celery / Supabase Python | 5.6.3 / 2.31.0 |
| React / TypeScript / Vite | 19.2.8 / 5.8.3 / 6.4.3 |
| 后端应用 Python 文件 | 103（清理后） |
| 后端测试文件 | 32（清理后） |
| 前端 TS/TSX 文件 | 25（清理后） |
| SQL migration | 26 |

## 环境开关快照

基线读取根 `.env` 时，`VITE_MOCK_APP=false`、`CELERY_TASK_ALWAYS_EAGER=false`；`MOCK_EXTERNAL_APIS` 与 `ENABLE_MINERU` 未显式设置。后两者按 `Settings` 默认值分别解析为 `false` 与 `true`。清理后前端已删除 `VITE_MOCK_APP` 分支，该历史变量即使仍存在于本地 `.env` 也不再影响运行。

本轮没有启动或验证 Supabase、PostgreSQL/pgvector、Storage、Redis、Celery Worker、MinerU、真实 Chat/Embedding 或 SMTP，因此这些服务的可用性均为 **N/A（未执行）**。

## 清理前基线证据

| 检查 | 结果 |
| --- | --- |
| 后端完整测试 | `170 passed, 3 warnings`，15.47s |
| 前端 lint（`tsc --noEmit`） | 通过 |
| 前端生产 build | 通过，7.46s |
| 最大构建 chunk | 509.75 kB（gzip 150.70 kB），Vite 警告 |
| OpenAPI | 147 paths / 177 operations |
| 无前缀业务 path | 68 |
| `/api/workbench/*` path | 10 |

基线 OpenAPI：[`openapi-before.json`](./openapi-before.json)。

## 实施结果

1. 业务路由只挂载在 `/api/v1`；`/health` 保持无版本健康检查。
2. 删除无认证 `/api/workbench/*` 路由、占位数据和对应测试。
3. 删除旧 `/outline/generate` 与 `/quiz/generate`，分别统一到 `/artifacts/*` 与 `/exams/*`。
4. 删除 `/exams/attempts/*` 镜像，作答统一到 `/exam-attempts/*`。
5. 考试与复习计划删除同步 HTTP 生成入口，只保留 `/generations` 异步入口；内部 service 仍供 Worker 和助手编排使用。
6. 抽取 generation task 公共实现，统一规范化 SHA-256 指纹、活跃任务幂等查询与持久任务创建。
7. 删除 4 个无人调用的旧 agent 占位模块、旧静态 plan coverage 脚本、旧常量/日志/eval 包装和未使用同步 LLM/parse 包装。
8. 删除前端未使用的 `gsap`、`@gsap/react` 依赖和 11 个无外部调用的类型导出；删除未调用的同步 `createExam` 客户端方法。
9. 删除错题本公开路由残留和文档术语；`wrong_answers` 历史表与隐私导出/删除覆盖继续保留。
10. 更新动态 E2E 脚本为唯一 `/api/v1` 路径及考试/计划异步生成流程；没有在本轮执行真实 E2E。

## 清理后契约

清理后 OpenAPI 为 62 paths / 75 operations，较基线移除 85 paths，无新增兼容别名。移除项由 68 条无前缀镜像、10 条 Workbench Mock 和 7 条重复/同步旧入口组成。

清理后 OpenAPI：[`openapi-after.json`](./openapi-after.json)。页面到 API、Service、表和测试的映射见 [`API_ACCEPTANCE_MATRIX.md`](./API_ACCEPTANCE_MATRIX.md)。

## 回归证据

| 检查 | 清理后结果 |
| --- | --- |
| 受影响后端测试 | `35 passed, 1 warning` |
| 后端完整测试 | `170 passed, 3 warnings`，17.50s |
| Ruff `F` 类（未使用 import/未定义名） | 通过，0 条 |
| Vulture（80%） | 仅 2 个 Pydantic validator `cls` 反射误报 |
| Knip | 通过，0 个未使用依赖/导出 |
| 前端 lint | 通过 |
| 前端生产 build | 通过，6.27s；最大 chunk 509.37 kB（gzip 150.58 kB），保留 Vite 警告 |

## 已知限制与后续门禁

- 本轮未执行真实 E2E，不能证明 Provider、MinerU、pgvector、RLS、邮件、延迟或成本。
- Ruff 全规则首次扫描有 214 条，其中大量为 FastAPI `Depends` 的 B008 规则冲突、导入排序与宽泛异常历史债；本轮将未使用符号作为硬门禁，没有用自动格式化扩大改动范围。
- Vite 最大 chunk 基线超过 500 kB，属于后续性能优化候选。
- `/api/v1/materials/upload` 同步接口仍存在，当前只由后端处理链路测试使用；正式前端与 E2E 已统一使用 `/materials/uploads`。它不在本轮点名的考试/计划入口合并范围，列为后续迁移候选。
- 真实性能、Token 与成本：N/A；不能写为 0。

## 完成判定

阶段 1、2、3 和 9 的代码、契约与文档工作完成后，最终门禁必须同时满足：后端完整测试通过、前端 lint/build 通过、Knip/Ruff F 通过、OpenAPI 可重新生成、仓库中不再存在 Workbench/旧错题本公开入口引用。
