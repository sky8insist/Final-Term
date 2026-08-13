# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

主要用户是备考阶段的学生。他们需要在有限时间内整理课程资料、与 AI 协作学习、生成练习、回顾错题并执行复习计划。

## Product Purpose

AI 学习工作台把分散的学习资料与复习活动组织在同一工作空间中，帮助学生从资料进入理解、练习、纠错和计划执行的连续流程。完成认证后才能进入工作台。

## Positioning

产品以学习科目为工作上下文，将资料处理、检索问答、思维导图、考试练习、错题和复习计划连接成可持续推进的学习闭环。

## Operating Context

用户通过浏览器使用产品，以邮箱注册和登录。注册需要完成邮箱验证；认证成功后进入按科目组织的学习工作台。系统由 React/Vite 前端、FastAPI 后端和 Supabase Auth/数据库构成。

## Capabilities and Constraints

- 认证包含登录、注册、邮箱验证提示、重发验证邮件、忘记密码、密码重置、会话恢复和退出登录。
- 不提供免登录体验或演示入口；所有工作台路由均受认证保护。
- 前端使用 Supabase 的公开 URL 与 anon key，不得暴露 service role key 或其他服务端机密。
- FastAPI 业务接口使用 Supabase access token 作为 Bearer token，并通过 `/api/v1/auth/me` 返回当前用户。
- 仓库中现有的学习科目和业务页面功能、术语及接口行为需要保留。

## Evidence on Hand

- 现有前端页面与状态管理位于 `frontend/src`。
- 认证后端契约位于 `backend/app/api/auth.py` 和 `backend/app/api/deps.py`。
- Supabase 环境变量约定记录于 `frontend/.env.example` 与根目录 `.env.example`。
- 当前没有可使用的品牌图片、客户证言或量化效果证明，后续界面不得虚构这些内容。

## Product Principles

- 先建立可信身份，再进入个人学习空间。
- 每个认证状态都必须告诉用户发生了什么以及下一步该做什么。
- 学习流程按科目保持上下文连续，避免在工具之间丢失目标。
- 动效服务于方向感和状态反馈，不遮挡任务或拖慢操作。

## Accessibility & Inclusion

认证流程必须支持键盘操作、清晰焦点、语义化表单、可读错误信息和 `prefers-reduced-motion` 动效降级；桌面与移动端均可完成全部流程。
