# 学习记录真实浏览器验收

日期：2026-10-27。**最终结论：限定范围通过，Edge 11/11、Chrome 11/11，共22项。**

范围是 `/learning-metrics` 和相邻登录/退出/账号隔离流程。不是全项目业务、生产环境、移动端或真人学习效果验收。以下浏览器测试使用真实渲染、实际HTTP、本地Supabase密码登录和后端正常JWT校验，没有TestClient、身份覆盖或预置登录存储。

## 环境与证据

| 项目 | 实际值 |
| --- | --- |
| 系统/模式 | Windows，本机安装的无头Edge/Chrome，新建隔离浏览器上下文 |
| Edge | 156.0.4314.42，11项passed，pageErrorCount=0 |
| Chrome | 156.0.8078.47，11项passed，pageErrorCount=0 |
| 驱动 | Playwright Python 1.64.1，可选requirements-browser.txt |
| 尺寸 | 1365×900、1024×768；产品现有桌面支持范围 |
| 前后端 | 脚本自有随机空闲端口的Vite/uvicorn，正常app.main及get_current_user |
| 认证/数据 | 本地Supabase真实密码登录/JWT；新建临时账号，23条推荐/65条行动及合成指标 |
| 异常模拟 | 仅明确的503与延时场景拦截请求；延时仍取真实API响应，正常场景不替换业务数据 |

内置Browser插件已按技能读取并尝试发现执行工具，但当前没有可调用的对应工具。因此本次使用独立本机浏览器，不控制现有内置标签页或用户浏览器会话。

可核对的文件：

- [Edge报告](metrics_browser_20261027/edge/report.json)、[Chrome报告](metrics_browser_20261027/chrome/report.json)。
- [源码与最终报告/截图的SHA256索引](metrics_browser_20261027/evidence.json)。哈希绑定当前被测源码和文件字节，不证明外部机构认证。
- [1365桌面](metrics_browser_20261027/edge/desktop-1365.png)、[1024桌面](metrics_browser_20261027/edge/desktop-1024.png)、[键盘详情](metrics_browser_20261027/edge/audit-keyboard.png)、[空账号](metrics_browser_20261027/chrome/empty-account.png)。截图已实际查看，非生成示意图。
- [首轮失败记录](metrics_browser_20261027/initial/report.json)。首轮末尾Auth管理员清理报错导致自动报告中断，该记录由已捕获输出重建，明确保留“未记录”的运行时计数，不伪造首轮完整报告。

## 检查矩阵

| ID | 实际操作与断言 | Edge | Chrome |
| --- | --- | --- | --- |
| B01 | 未登录访问指标页→登录重定向→填写临时账号正常密码登录，进入指标页 | 通过 | 通过 |
| B02 | 默认30天、四类安排、6/10=60%覆盖率、历史首屏20条 | 通过 | 通过 |
| B03 | 旧7天请求延迟返回，切换90天后仍保持新窗口结果 | 通过 | 通过 |
| B04 | 推荐20→23条；键盘Enter打开详情并聚焦标题；行动30→60→65条，Space展开依据 | 通过 | 通过 |
| B05 | 真浏览器reload后URL与选中详情保持，事件从首屏重新读取 | 通过 | 通过 |
| B06 | 关闭详情后焦点恢复到对应历史行的“查看”按钮 | 通过 | 通过 |
| B07 | 显式503覆盖率错误，其余指标仍显示；点击重读恢复60%与无错误提示 | 通过 | 通过 |
| B08 | 两档桌面宽度控件可见，document不横向溢出，保存截图 | 通过 | 通过 |
| B09 | 同一浏览器退出并登录空账号，不残留前账号推荐，空值不冒充0% | 通过 | 通过 |
| B10 | 空账号打开前账号详情真实返回404；关闭错误详情后聚焦历史标题 | 通过 | 通过 |
| B11 | 观察到真实auth/token成功及Bearer API请求，且没有pageerror | 通过 | 通过 |

## 首轮发现及修复

首轮真实浏览器中，关闭详情后面板隐藏，焦点随隐藏按钮丢失，未返回原历史行。修复为：维护已挂载行的按钮引用和上次选中ID，在关闭或返回到列表时优先恢复对应按钮；原行不在当前页或记录不可访问时，回退聚焦历史标题。标题具备tabIndex=-1与可见焦点样式，不强行刷新或执行旧建议。

同一确认轮分别在Edge/Chrome执行全部检查，B06和B10均通过；没有以单元模拟代替DOM焦点断言。

## 清理问题与验证边界

首轮直接调用Auth管理员删除带合成学习记录的临时账号返回数据库500；本轮未查明其根因，也未将其归因成某个已确认的产品漏洞。已用预先确认的精确测试ID通过本地SQL完成清理，检查该账号与五类学习/审计数据为零。确认轮脚本改为验证生成邮箱对应ID后SQL删除，按确切用户UUID清理本人Redis快照，并停止自身服务。最终没有遗留本轮浏览器测试账号。

这只证明测试夹具可被安全清理，不代替产品“删除账号”流程。该产品流程会先清学习数据，应在Security/Privacy专项单独验证，不能把直接管理员接口500隐藏在“验收全部通过”中。正常Auth服务自身日志未承诺清除。

其他边界：两款浏览器均为Chromium家族；没有Firefox/Safari/真实移动设备或人工用户验收。登录为本地真实JWT，不代表生产JWT配置正确。指标和时间均为合成夹具，不代表长期效果。没有调用真实模型或付费服务，未验收持续Worker、生产容量或P95。

## 复跑

backend目录，已安装历史迁移至057、前端依赖和本机Edge/Chrome，并配置本地Supabase/Redis/数据库：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe scripts/verify_metrics_browser.py --browser edge --output-dir ../docs/acceptance/metrics_browser_20261027/edge
.\.venv\Scripts\python.exe scripts/verify_metrics_browser.py --browser chrome --output-dir ../docs/acceptance/metrics_browser_20261027/chrome
```

脚本拒绝非本机数据库/Supabase/Redis，不修改实际.env，不使用已有浏览器profile，不保存认证storage_state/HAR。密码只在内存和本机登录表单中使用；报告不写密码/令牌。新建账号和合成数据先提交供真实API跨连接读取，最终按生成邮箱和精确ID清理。

本轮前端33项Node回归、lint/build及后端Ruff F通过，最大chunk255.61 kB，学习记录页18.69 kB。最近完整后端基线为886 passed/3 warnings，本轮未修改后端业务代码，未重复跑完整套件。服务只启动/停止脚本自己的进程，现有业务服务未重启。
