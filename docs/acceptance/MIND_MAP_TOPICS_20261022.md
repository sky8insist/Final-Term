# Mind Map Topic 与学习状态验收 — 2026-10-22

本轮完成稳定人工关联、实时学习投影和学习入口。指南的权威先修边、新材料 graph diff 仍待后续实现。

## 实现

- 049 建立 mind_map_topic_links：artifact/node 主键、本人同科目复合外键、完整节点快照、关联版本；认证用户只读，两个 RPC 仅服务角色执行。新表纳入隐私导出，导图删除级联。
- 绑定/解绑在事务内锁定导图，校验导图与关联版本，再提升版本；解绑保留关联行。节点内容修改或 Topic 归档使关联失效，其他节点保留；Topic 改名不改变身份。
- 按 Topic 的不可变 knowledge_key 读取 knowledge_mastery，复用 learner-state-v1，移除名称近似匹配。界面不使用模型生成的掌握度。覆盖不等于掌握，无作答记录不展示默认 50%；关联和读取不写覆盖/掌握记录。
- 节点详情展示 Mastery、数据置信度、自报信心、上次/下次复习、到期卡片、误解提示、待考考试及范围权重、来源引用。节点颜色和文字区分已覆盖/已掌握/需巩固。
- 节点进入 Guided Session；真实考试映射进入完整考试 Study Plan，无考试时显示空状态。未实现任意节点独立计划。
- 保留 Turn Into：只继承当前有效节点 Topic，未关联/失效时为空；来源与实时版本不一致拒绝转换。绑定/解绑提升导图版本，原转换来源需重新确认。
- 状态绕过 workspace 缓存；加载、保存关联、窗口焦点恢复和手动刷新时读取，非实时推送。内容/状态版本不一致最多再取一次；科目切换和请求序号防止迟到结果覆盖。刷新失败关闭旧详情并保留重试。

## 验证

| 检查 | 结果 |
|---|---|
| 新增 Topic 回归 | 21 passed |
| Mind Map / Topic / Conversion 专项 | 73 passed |
| 完整后端 pytest | 703 passed，3 项既有依赖弃用警告 |
| Ruff F、离线 quality gate | 通过 |
| 前端 TypeScript / Vite build | 通过，最大 chunk 256.38 kB |
| UI 静态检测 | 两个条件样式合并提示已代码核对 |
| git diff --check | 通过 |

单测涵盖无评估不显示默认分数、Covered/Mastered 阈值、误解/回忆风险、RPC 错误状态、API 身份和参数/额外字段拒绝、匿名拒绝、节点精准继承及转换版本冲突。原导图与转换测试已适配实时投影契约。

本地 PostgreSQL 已安装 049。真实事务验证跨用户/科目/节点拒绝、双版本冲突、无覆盖/掌握写入、不可变 key、改名保持/归档失效、due 卡片与考试状态、逐节点失效/重绑/解绑、认证用户只读 RLS/私有 RPC 拒绝及导图删除级联。所有测试行回滚。

实际本地 Supabase 只读 API 返回 200、缺失 ID 404、匿名 401；认证依赖为测试覆盖。未写真实用户绑定，未调用模型或付费服务。

静态提示分别来自 loading 的蓝色进度条与同一行白底灰字、节点蓝底/蓝色深字和白底灰黑文字的互斥分支；代码核对没有提示描述的同元素组合。没有可调用浏览器工具，未将静态核对视作浏览器验收。

## 复跑与部署

在 backend 目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_mind_map_topics.py --api
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
```

本地首次安装缺失 049 可加 `--apply`；脚本拒绝远端数据库。其他部署环境按历史依赖顺序安装 049 后部署 API/前端。没有新增 Worker/Beat 调度，本次未重启服务、未修改实际 `.env` 或用户技术指南。

## 剩余范围

权威 prerequisite/Topic Graph 编辑、新材料 graph diff、独立节点 Study Plan、自动有证据 Topic 提案、真实浏览器键盘/布局/JWT/模型验收待补。置信度沿用现有投影，并非新校准的正确概率。下一阶段为 Memory / Learner Profile。
