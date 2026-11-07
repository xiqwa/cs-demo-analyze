# INF-02 交付记录

任务 ID：INF-02。按 INF-02-A/B/C/D 完成；未扩展到 Demo 解析或 AI。

| 子项 | 交付 |
| --- | --- |
| INF-02-A | [契约](INF-02-contract.md)：系统用户数据路径、迁移命令、健康检查、日志字段；[健康检查 JSON Schema](health-response.schema.json)，与 Pydantic/OpenAPI 一致性测试 |
| INF-02-B | roundmind/config.py、database.py；SQLAlchemy/SQLite 连接与 PRAGMA；migrations/env.py 和 0001_initial；启动 auto/check 策略；CLI 升级/查询/显式回滚 |
| INF-02-C | logging.py、middleware.py、diagnostics.py、serve.py；JSON 日志、请求 ID 隔离、递归脱敏、按 UTF-8 字节轮转、安全故障回退、本地诊断 ZIP |
| INF-02-D | tests/test_database.py、test_health.py、test_logging.py、test_cli.py 及 fixture；Linux/Windows CI；[运维说明](INF-02-operations.md)与 README |

## 接口影响

GET /api/v1/health 保留 data/meta，新增 database；数据库就绪返回 200/ok，否则 503/degraded。响应模型 HealthResponse 同时声明 200、503，request_id 格式为 UUID。前端 health.ts 和契约测试已同步。未知路径和未捕获异常使用统一错误信封。没有新增可远程读取数据库、日志或导出文件的 HTTP 接口；诊断导出只通过本地 CLI。

初始库：demo_files、matches、rounds、events，含哈希唯一、外键、回合唯一和 Tick 索引；其余领域表随后续任务迁移。不生成示例比赛。

## 验证结果

- 先写契约、测试，再实现；首次收集测试因 create_app/基础设施模块尚未实现而失败，随后补实现。
- `PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q --junitxml=artifacts/api-tests.xml`：**37 passed**，1 项 Starlette/AnyIO 依赖弃用警告。JUnit 在 artifacts/api-tests.xml。
- `npm test`：**4 passed**。
- `npm run build`：TypeScript 与 Vite 构建成功。
- 后端覆盖路径默认值/相对路径拒绝、连接 PRAGMA、哈希去重/外键、升级/回滚/重升、保留数据的幂等、首次与后续升级失败、回滚失败的事务恢复、并发升级、未知版本拒绝接管、check 模式不建库、健康检查503、OpenAPI/schema一致性、请求并发隔离、500脱敏、日志凭据/路径脱敏、写日志失败不泄露、UTF-8轮转、导出边界/坏行/符号链接、不覆盖诊断包和 CLI 退出码。
- 实际启动 `roundmind.serve`，Vite 代理返回 database.ready/0001_initial；真实数据目录为本轮隔离开发目录，不读取原始 Demo。
- 系统 Chromium + Playwright：健康在线、503 离线提示、重新连接、Demo 库往返导航、390px 无横向溢出、无页面运行错误，均通过。截图：artifacts/inf02-dashboard.png。
- 实际 CLI 生成 artifacts/inf02-diagnostics.zip，包内仅 manifest.json 与 logs.jsonl，导出时 5 条有效记录；不包含数据库。

## 已知限制

Windows API CI 与 Tauri 编译 job 已配置但未在本机执行，不能视为通过。多 worker 文件日志轮转不支持；CLI 事件写 stderr，不收进应用文件诊断包。健康检查只验证可读与版本，不代替 SQLite 完整性检查。迁移前备份与恢复为人工运维流程；本版 downgrade base 会删除四张业务表数据，命令须显式 --allow-data-loss。数据目录要求本机文件系统；Windows ACL 使用系统继承规则。诊断包是有界日志摘录，不是数据库备份或原子日志快照。任意自由文本的无标记个人信息不承诺被正则完全识别。

无 Demo 回放模块，本轮回放同步和证据事件跳转检查不适用。既有生产桌面后端启动/鉴权与安装包限制仍存在。

下一任务：PAR-01 导入/哈希/去重，先写接口与测试，再接真实用户授权文件。
