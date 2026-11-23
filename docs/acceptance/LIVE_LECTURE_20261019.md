# Live Lecture / 课堂录音第一轮 — 2026-10-19

依据指南的 Record → Audio Segment → Transcript → Topic Alignment → Knowledge Base，以及 P3 第 16 项。本轮是录制结束后的批处理工作台；持续上传音频切片、实时字幕、自动分题和自动 Topic 映射尚未实现。

## 可审查的交付范围

`/lectures` 增加浏览器录音、暂停/继续、停止后回听/下载、上传已有音频和挂接已有音频资料。停止后的 Blob 按账户/科目保存到 IndexedDB，上传与课堂创建成功后再删除；存储失败时提示下载保留。录音中离开页面停止麦克风，权限请求晚于卸载返回时也释放音轨；刷新/关闭前提醒停止并下载。录音进行中仍可能因刷新/崩溃丢失，未实现持久化每秒音频或断点上传。本地草稿不随云端账号删除自动清除，用户可明确放弃。

音频复用已有 ingestion/Worker、静音附近分段、audio_segments 成功转录缓存及知识库摄取。课堂本身不复制音频或新建第二套转录队列；原上传失败后的重试、消息投递和取消恢复仍遵循旧摄取实现。页面显示分段/任务进度，支持失败任务在次数允许时重试，不承诺转录/计费恰好一次或新增 outbox 恢复。

转录每页 50 条，API 最大 100；按 sequence_index/id 稳定排序，具体 blockId 可直接定位所在页。原音频通过既有短时签名 URL 回听、刷新链接、跳到片段起点；过期或原文件已清理时提示。真实音频播放、麦克风/后台计时及 IndexedDB 行为未做浏览器验收。

## 来源与 Topic

045 新增 lectures、lecture_topic_links。挂接 RPC 限本人同科目的音频 MIME，按 user/material 去重；再次挂接返回已有课堂，不用新名称覆盖旧记录。source_kind 是客户端声明的录制/上传方式，不是声源真实性证明。

人工对齐使用课堂版本 CAS；链接冻结原始文本和起止时间。原文或时间变化、Topic 归档时，旧映射不会作为当前 Topic 返回或继承。支持取消关联；不覆盖原转录、不自动写覆盖状态或 Mastery。这里的手动标注不等于自动转录主题分割，也没有按 Topic 自动重建检索索引。既有摄取先将原文入知识库，人工映射在其后完成。

复合外键绑定课堂/来源块/资料/Topic 的 user/subject。认证用户只读本人新表，变更 RPC 仅 service_role。隐私导出纳入两表；资料、课程或账号删除沿既有父级外键清理，归档 Topic 保留历史链接但不作为有效映射。

## 转录与时间修正

- 新增 audio/webm（含 codecs 参数）上传规范化与 EBML 文件头检查。FFprobe 没有 format.duration 时回退扫描音频包 PTS/duration，拒绝 NaN/Infinity/非正时长；既有服务器最大音频时长仍生效。
- WebM 包括短音频统一解码为 WAV 后发送给既有 ASR。该行为使用模拟二进制响应验证，本机未运行真实转码。
- 新解析音频的 source_hash 纳入音频分段/绝对时间，避免不同分段中重复句子相互覆盖。旧音频不自动重建，历史时间或重复句问题仍需回听核对；失败材料重新处理或历史重建的完整替换/引用迁移仍待后续摄取模块处理。
- ASR 时间需要有限、非负、有序并处于物理分段内。起点越界拒绝；末尾最多 0.5 秒的舍入误差对齐物理末尾，更大越界拒绝。没有逐句时间时使用物理分段窗口并明确标记 segment_window，不能称逐句精确定位。
- 服务没有提供数值置信度时保存 null，不默认 100%；布尔值不作为概率。已提供的数字仍只是服务报告、未经校准；历史默认值不冒充当前识别置信度。

## 片段 → 学习材料

统一 ConversionSource 的 material 来源可选 blockIds（1–30、不可重复，仅限 material）。后端核对每个 ID 都来自所选资料、本人同科目，再取得 canonical 原文/时间。所选片段仅继承仍匹配原文/时间且未归档的人工 Topic，冻结来源后复用原四类目标 Notes / Flashcards / MindMap / Quiz。

未引入 lecture 专用来源类型或实时 Tutor 路径，不能把整堂课前 30 块的转换当作全量长课总结。旧调用不提供 blockIds 时行为、参数指纹和浏览器待确认请求键保持兼容；有 blockIds 的待确认键独立隔离。转换历史可返回具体课堂/blockId，超过第一页也能定位。原子发布、取消和任务幂等仍使用 043。

## 验证证据

- 新增 **29 项**后端回归；完整 **521 passed, 3 warnings**。覆盖 WebM MIME/文件头、缺少 duration 的包时间回退、非有限时长、短 WebM 转 WAV、重复句来源标识、越界/窗口/未知置信度、所选块范围、旧指纹兼容、有效 Topic 继承、API 身份/参数/分页。音频二进制调用、ASR 输出使用测试响应，没有付费转录。
- Ruff F、统一 quality gate、前端 lint/build 通过；最大 chunk **254.95 kB**。UI 检测一条互斥条件 className 的灰字/蓝底提示，经代码核对；没有浏览器工具，未声明渲染、录音权限、播放、草稿及键盘 E2E 通过。
- `verify_lectures.py --api` 使用真实本地 PostgreSQL 验证音频限制/跨用户归属/重复挂接、Topic CAS/跨科目/归档/解除、原文变化失效、不改变 Mastery、121 段分页和指定 block 定位、复合外键、RLS 与私有 RPC。临时行全部回滚。
- 真实 Supabase 只读课堂、音频资料列表、能力与转换历史查询成功，跨用户科目 404、匿名 401。身份为 TestClient 覆盖，不是真实 JWT；没有实际用户音频写入、没有 ASR 调用。
- `git diff --check` 通过。实际 .env 和用户技术指南未修改；未重启现有服务。

## 当前运行限制与部署顺序

本机检查结果：**FFmpeg=False、ffprobe=False**。因此真实解码、ASR、长音频断点恢复、存储/Worker 持续事件链路未验收。能力 API 返回处理不可用，前端禁用新音频上传处理，但仍可录音下载和查看已有转录。能力只检测 API 进程，分布式环境需确保 Worker 同样具备工具，不能当作 ASR 模型或 Worker 健康证明。

部署前需要历史依赖（含 020/029/040/042/043），安装 045，再将 FFmpeg/ffprobe 配置到 API/Worker 可执行 PATH，配置可用的真实 ASR 服务并重启后端/Worker。未新增二进制下载器或修改实际环境。本地 045 已安装，但服务未重启。

复跑（backend 目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests scripts --select F
.\.venv\Scripts\python.exe scripts/run_quality_eval.py
.\.venv\Scripts\python.exe scripts/verify_lectures.py --api
```

`--apply` 仅允许 localhost，安装缺失 045，或刷新本模块同签名 RPC；不是通用 schema 升级工具。下一建议 Materials / Ingestion（用途、阶段恢复、章节/Topic 提案、上传后 Notes），并补齐音频依赖与真实链路。实时字幕、自动 Topic 分割、说话人精度、真实 WER/时间偏差/校准、浏览器/JWT 与长课内存性能保留待办。
