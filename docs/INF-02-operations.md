# INF-02 运维说明

对应 INF-02-A/B/C/D。数据库和日志均在本地，所有命令在仓库根目录执行。需要 Python 3.12。

## 安装与启动

Linux/macOS：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.txt
export PYTHONPATH=apps/api
# 可选；必须为绝对路径。未设置时使用系统用户数据目录。
export ROUNDMIND_DATA_DIR="$HOME/.local/share/RoundMind"
.venv/bin/python -m roundmind.serve
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps/api/requirements.txt
$env:PYTHONPATH = "apps/api"
# 默认就是 LOCALAPPDATA 下的 RoundMind，此处展示自定义配置方式。
$env:ROUNDMIND_DATA_DIR = Join-Path $env:LOCALAPPDATA "RoundMind"
.venv\Scripts\python.exe -m roundmind.serve
```

标准启动器固定绑定 127.0.0.1:8765，单 worker，关闭原始 access log；Uvicorn 与 SQLAlchemy/Alembic 的控制台日志采用安全 JSON 格式（不保留自由文本、SQL、堆栈）。不要使用默认 Uvicorn 日志配置作为运维启动方式。前端另行执行 `npm run dev`，访问 http://localhost:5173 。

程序启动前完成目录初始化和迁移，然后才接收请求。`ROUNDMIND_MIGRATION_MODE=auto` 默认升级到 head；设为 `check` 时不迁移、不创建数据库，版本不符则退出。日志文件无法初始化也会停止启动。运行中日志写入失败仅输出带请求 ID 的 `log_write_failed` 安全 JSON 到 stderr，不把原始异常或日志参数作为回退输出；运维应处理磁盘满/权限问题。

应用文件日志由服务进程独占；CLI 事件以相同 JSON 格式写到 stderr，命令结果写 stdout，避免 CLI 与服务竞争文件轮转。诊断 ZIP 仅收集应用文件日志，不收集 CLI stderr 或 Uvicorn 控制台日志。多服务进程和多 worker 日志聚合不属于本版能力。

## 升级与版本查询

以下以 `.venv/bin/python` 表示解释器；Windows 替换为 `.venv\Scripts\python.exe`。

```bash
.venv/bin/python -m roundmind.manage db current
.venv/bin/python -m roundmind.manage db upgrade
.venv/bin/python -m roundmind.manage db current
```

`current` 不创建缺失数据库；缺库时退出 1。存在但无版本/未知版本时命令正常输出 `schema_mismatch`（未知版本值不透传）。`upgrade` 可重复执行，保留已有数据。Alembic 脚本在 apps/api/migrations，必须通过管理命令或启动流程运行；直接使用没有外部连接的 Alembic CLI 会拒绝执行，以免绕过连接 PRAGMA 和事务策略。

每个新修订需要补齐 upgrade/downgrade、测试，并同步 HEAD_REVISION、健康检查 schema 与前端契约。本版只包含 `0001_initial`；不自动 stamp 现有未知数据库。`BEGIN IMMEDIATE` 加 5 秒忙等待控制迁移写锁；首次 WAL 切换遇 SQLITE_BUSY/LOCKED 有限重试。超时退出，不无限重试、不删除数据库。

## 备份、回滚与恢复

升级、回滚前停止本地服务并备份。SQLite 使用 WAL；不要在服务写入时只复制主 .sqlite3 文件而遗漏 WAL。停止进程后可用 SQLite backup API 建立完整一致备份。示例（设置 BACKUP 为新的绝对路径，不放入日志或诊断包）：

```bash
export BACKUP="$HOME/roundmind-before-upgrade.sqlite3"
.venv/bin/python - <<'PY'
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from roundmind.config import Settings
source = Settings.from_env().database_path
backup = Path(os.environ['BACKUP']).expanduser()
if not backup.is_absolute():
    raise ValueError('absolute_backup_path_required')
# 明确拒绝覆盖；文件以 0600 创建。
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.close(fd)
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
    with closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
PY
```

PowerShell 可先设置 `$env:BACKUP`，并以 Python 脚本文件或 here-string 管道执行相同 Python 内容。

本版回滚到 base 会删除 events、rounds、matches、demo_files 及其中数据；必须显式带参数：

```bash
.venv/bin/python -m roundmind.manage db downgrade base --allow-data-loss
```

不带参数时退出 2。回滚只影响本库，不访问、不删除原始 Demo 文件。需要恢复时，保持服务停止，将当前整个 db 目录先重命名保留（包括 WAL/SHM），创建新的 db 目录，将一致备份放到 `roundmind.sqlite3`，避免把旧 WAL 与备份混用。再执行 `db current`、`db upgrade`，最后启动服务。不可在运行时替换数据库文件。

失败事务：业务表 DDL/DML 与 alembic_version 同一事务，失败自动回滚；首次失败可留下空数据库文件和 WAL 设置，不能视为迁移成功。升级和回滚失败测试均覆盖表、数据或版本恢复。不自动恢复备份、不静默重建库。

## 健康检查与问题排查

`GET http://127.0.0.1:8765/api/v1/health`：200 + ready 才表示服务就绪。运行中缺库、损坏或无法读取时返回 503/unavailable，版本不符返回 503/schema_mismatch；不会自动重建数据库，不输出真实路径。健康检查使用独立只读连接、1 秒 busy timeout；业务连接 5 秒 busy timeout。

遇到 migration_failed：先停止服务，检查数据目录的写权限、磁盘空间和占用进程；用 db current 检查版本，不要删除 alembic_version 或强行 stamp。unmanaged_database 表示数据库已有表但缺少有效版本，不会被接管；应核实备份/数据来源。schema_mismatch 表示启动 check 未通过或升级后的库不符合程序期望版本。日志不保存原始异常和 SQL，因此检查应结合权限、空间、锁状态与备份进行。

request_id 从服务端生成，响应头 X-Request-ID、JSON API 信封和 request_completed 日志一致。未知路径记录为 `<unmatched>`；不记录实际请求路径、查询参数、头和请求体。HTML 文档页与 CORS 预检响应仍保留其原生响应体，关联 ID 在响应头。未发送响应前的未捕获异常返回统一 500 JSON；已经发送流响应后的错误不能替换响应体，但仍记录失败日志。

## 诊断导出

```bash
.venv/bin/python -m roundmind.manage diagnostics export --output /absolute/path/roundmind-diagnostics.zip
```

Windows 的 `--output` 使用如 `C:\Users\me\Desktop\roundmind-diagnostics.zip` 的绝对路径。父目录必须已存在。相同文件名拒绝覆盖，退出 1/output_exists。导出只写本地文件，不会上传。包内只有 manifest.json、logs.jsonl：最多读取 4 个固定文件各末尾 1 MiB、保留最近 1000 条有效记录、再次字段筛选及递归脱敏；跳过符号链接、坏行、不完整尾行和轮转时已经消失的文件。不是全量、原子快照或数据库备份。

不收集数据库、Demo、API 密钥、配置、环境变量或任意目录。不要手工把这些文件塞入诊断包。自由文本中的无标记个人信息不能依赖正则完全识别，新增业务日志仍应使用固定事件与必要字段。

## 验证和 CI

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q --junitxml=artifacts/api-tests.xml
npm test
npm run build
```

CI 的 API job 在 Ubuntu 与 Windows 使用 Python 3.12 运行完整测试并上传 JUnit；Web job 验证前端；既有 Windows Tauri 壳编译 job 保留。Windows 上 POSIX 权限测试不适用，无法创建符号链接时对应测试明确 skip。当前 Linux 本地结果不代表远程 Windows CI 已通过。
