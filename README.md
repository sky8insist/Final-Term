# Exam AI Assistant

面向课程复习的学习工作台，使用 FastAPI、React、Supabase、pgvector 和 Celery。支持资料解析、带来源的检索问答、课程知识点、引导学习、考试、闪卡、复习计划与学习记录。

## 当前进度

- [交接文档](HANDOFF.md)：当前版本、部署要求及下一步。
- [优化进度](docs/OPTIMIZATION_PROGRESS.md)：模块状态与未完成范围。
- [验收索引](docs/acceptance/README.md)：测试范围和证据。
- [技术指南](PROJECT_TECHNICAL_INTERVIEW_GUIDE.md)：项目需求依据。

最新增量为上传孤儿文件恢复及图索引超时保护。普通回归、使用临时数据的本地验收、真实模型质量和生产运行分别记录；通过回归不代表生产或长期学习效果已经验收。

## 启动

依赖 Python 3.12+、Node.js 22、PostgreSQL/pgvector、Supabase Auth/Storage 和 Redis。项目文本统一为 UTF-8。

1. 将根目录 `config.env.template` 复制为 `.env`，填写数据库、认证及模型配置。前端从根目录读取 `VITE_*`，无需单独配置文件；其中不能填写服务端密钥。
2. 安装依赖：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

3. 本地 Supabase 使用 `supabase-project/config.env.template` 配置，运行 `scripts/start-local-supabase.ps1`。配置细节见 [Supabase 配置](supabase-project/CONFIG.md)。
4. 空库可在 backend 目录运行 `python scripts/e2e_acceptance.py --apply-migrations` 按序安装；已有库只执行尚未安装的迁移，避免重复建表。部署至本阶段至少需要 **061**。
5. 使用 `start-project.ps1` 启动 API 与前端；异步任务另运行 `scripts/dev-worker.ps1` 和 Celery Beat。Windows 也提供 `一键启动.cmd` 与 `一键停止.cmd`。

启动器不自动启动数据库、Redis、Worker 或 Beat。队列部署见 [材料摄取说明](docs/MATERIAL_INGESTION_JOBS.md)；升级时须先排空旧版材料 Worker，再部署迁移及新代码。

## 数据处理与安全

上传先登记持久意图，再写入私有 Storage，最后原子登记文件清单与处理任务。摄取有租约、心跳、解析/向量检查点和取消发布保护；检索只使用本人可访问的材料，回答保留来源。

上传恢复和历史数据清理默认关闭。先查看候选及保留策略，再通过部署配置启用。参见 [恢复与清理](docs/UPLOAD_RECOVERY.md)、[数据保留](docs/DATA_RETENTION.md)和[隐私验收](docs/acceptance/PRIVACY_INTEGRITY_20261027.md)。

`.env`、本机数据、数据库文件和运行日志不进入版本控制。课程资料、模型输出和用户数据不会作为默认公开示例发布。

## 验证

在 backend 目录运行：

```powershell
python -m pytest tests -q
python scripts/run_quality_eval.py
```

在 frontend 目录运行 `npm run lint` 和 `npm run build`。浏览器及外部服务验收依赖本地配置，其复跑命令和限制在各验收记录中说明。

后端入口为 `/api/v1`；交互接口文档位于运行中的 `/docs`。代码分为 `backend/app/api`、`services`、`worker` 与 `frontend/src`，数据库迁移位于 `backend/migrations`。
