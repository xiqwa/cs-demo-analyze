# INF-02-A 契约

状态：本轮实现基线。INF-02 只负责本地持久化、迁移、健康检查和可导出的运维日志，不提供 Demo 解析。

## 数据目录

优先使用 `ROUNDMIND_DATA_DIR`（非空、绝对路径，展开 `~` 后规范化）；未设置时 Windows 为 `%LOCALAPPDATA%/RoundMind`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/RoundMind`，macOS 为 `~/Library/Application Support/RoundMind`。拒绝相对路径。不会以当前工作目录或安装目录为隐式回退。数据库固定为 `data_dir/db/roundmind.sqlite3`，日志固定为 `data_dir/logs/roundmind.jsonl`。不接受独立的任意数据库 URL。

目录首次创建时 POSIX 模式 0700；数据库、日志与诊断包新建时 0600；不擅自修改既有父目录或 Windows ACL。仅支持本机文件系统；网络盘不在 WAL 支持范围。数据目录不保存原始 Demo；不自动删除用户文件。

## SQLite 与迁移

SQLAlchemy 连接统一使用 `foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout=5000`（毫秒）、`synchronous=NORMAL`；每次建立业务连接设置；健康检查/版本查询为独立只读连接，query_only=ON、busy timeout 1 秒，不切换 WAL。事务显式开始，连接不跨请求共享。写迁移以 `BEGIN IMMEDIATE` 串行化，DDL、业务数据及 alembic_version 在同一个事务中提交，失败全部回滚。

Alembic 唯一版本：`0001_initial`。首迁移建立 demo_files、matches、rounds、events 及外键、去重/回合索引，不创建演示比赛。其余领域表随对应任务迁移增加。

在根目录设置 `PYTHONPATH=apps/api` 后：

- `python -m roundmind.manage db upgrade`：升到当前 head，可重复执行。
- `python -m roundmind.manage db current`：只读查询实际/期望版本，不创建数据库。
- `python -m roundmind.manage db downgrade base --allow-data-loss`：运维显式回滚；本版将删除四张业务表及数据，保留空版本表。缺少参数时拒绝执行。
- `python -m roundmind.manage diagnostics export --output <absolute-path.zip>`：本地导出脱敏诊断包，不上传，不覆盖同名文件。

CLI 正常退出 0，失败退出 1，参数错误退出 2；输出 JSON 错误码，不输出原始异常/路径/SQL。迁移错误码包括 `migration_failed`、`unmanaged_database`、`schema_mismatch`。未知版本、无版本但有业务表的数据库不得自动 stamp 或重建。

`ROUNDMIND_MIGRATION_MODE=auto|check`（默认 auto）：启动时 auto 在接收请求前执行 upgrade；check 只验证现有库，缺库或版本不符直接启动失败。两种模式均不自动 downgrade。迁移或日志初始化失败则启动失败，不能报健康。单服务进程/单 Uvicorn worker；迁移锁解决 CLI 与启动的短时竞争，不宣称支持多进程日志轮转。

## /health schema

`GET /api/v1/health`，无需令牌；200 表示数据库可读且版本符合，503 表示运行中数据库失联或版本改变。延续原 data/meta 信封，增加 database。

```json
{"data":{"status":"ok","service":"roundmind-api","database":{"status":"ready","schema_revision":"0001_initial","expected_revision":"0001_initial"}},"meta":{"request_id":"UUID","version":"0.1.0"}}
```

503 时 `data.status="degraded"`，`database.status="unavailable"|"schema_mismatch"`；无法读取或未知版本时 schema_revision 为 null。schema_revision 只允许 null 或已知版本，不透传任意库内容。不暴露数据库路径、异常或 SQL。OpenAPI 的 HealthResponse 是权威机器 schema。健康检查使用只读连接，不重新创建被删除的数据库。

## JSON 日志字段表

每行一个 JSON 对象，UTF-8，UTC 时间。服务文件日志轮转，CLI/服务器自身控制台日志写 stderr。必有：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| timestamp | string | UTC ISO 8601 |
| level | string | INFO/WARNING/ERROR |
| event | string | 固定事件名，如 request_completed、startup_ready、migration_failed |
| request_id | string/null | 服务端生成 UUID；生命周期/CLI 为 null |

按事件可选：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| method | string | HTTP 方法 |
| route | string | 路由模板；未匹配为 `<unmatched>`，不记录原始 URL |
| status_code | integer | HTTP 状态 |
| duration_ms | number | 单调时钟耗时 |
| error_code | string | 稳定错误码，不记录原始异常 |
| revision | string/null | 已知迁移版本 |
| details | object | 经递归脱敏的额外上下文 |

request_id 总是由服务端生成，忽略外部 X-Request-ID；使用 ContextVar 隔离并在请求完成后恢复。所有 HTTP 响应均带 ID 头；健康检查和统一 JSON 错误体带同一 ID，并记录一条完成日志。不记录请求体、查询字符串、Cookie、Authorization、原始路径、SQL 参数、堆栈或异常文本。标准启动命令关闭 Uvicorn 原始访问日志，Uvicorn 错误日志使用同一安全 JSON 格式。HTML 文档页和 CORS 预检保持原生响应体。CLI JSON 日志写 stderr，不与服务共享轮转文件；运行中磁盘写失败只向 stderr 输出 log_write_failed 安全事件。

递归遮盖敏感字段（api_key/token/authorization/password/cookie/secret 等及变体）；字符串中遮盖 Bearer、sk- 密钥、常见键值凭据、URL、绝对 Unix/Windows/UNC 路径。结构化日志只接收有限字段；任意外部文本仍不得作为事件名。诊断导出再次脱敏，不把正则当作任意文本完全去标识化的保证。

轮转：单进程 RotatingFileHandler，5 MiB/文件，3 个备份，总计最多 4 个文件（单条记录限长）。诊断 ZIP 仅含 manifest.json 与 logs.jsonl；最多读取四个固定日志文件每个末尾 1 MiB，最多导出最近 1000 条有效记录。跳过符号链接、损坏行和不完整尾行；不包含数据库、Demo、配置、环境变量或原始路径。manifest 记录版本、生成时间、记录数和跳过行数。
