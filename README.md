# RoundMind CS2

依据《完整产品技术设计总稿 V1.0》实施。当前完成：**INF-01、INF-02（A/B/C/D）、枪法/逐枪复盘 Alpha 与 PAR-04 任务生命周期**。

当前交付 React + TypeScript 工作台、FastAPI 健康检查、Tauri 2 桌面壳、SQLite/Alembic 初始迁移、JSON 日志、诊断导出与 CI。现已接入 Demo 流式导入、哈希去重、独立进程解析、枪法报告、逐枪明细和回合 Tick 证据。生产界面无模拟比赛；地图回放与 AI 尚未实现。逐枪命中/瞄准误差/反应时间尚不支持，不生成推测评分。

## 在本机 Codex 打开

先安装 Git、Node.js 22+ 和 Python 3.12，然后在本机终端执行：

```bash
git clone https://github.com/xiqwa/cs-demo-analyze.git
cd cs-demo-analyze
```

在本机 Codex 选择“打开文件夹”，选择这个 `cs-demo-analyze` 目录。之后云端推送的新版本可在该目录执行 `git pull` 获取；本机未提交的修改应先保存。

Windows PowerShell 启动后端：

```powershell
npm ci
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps/api/requirements.txt
$env:PYTHONPATH = "apps/api"
.venv\Scripts\python.exe -m roundmind.serve
```

保持此终端运行，再开一个终端进入相同文件夹执行 `npm run dev`。浏览器打开 http://localhost:5173/#demos 即可选择你电脑上的 `.dem` 文件。

## 本地运行

需要 Node.js 22+、Python 3.12+。在仓库根目录：

```bash
npm ci
python -m venv .venv
# Windows 使用 .venv\Scripts\python.exe 替代 .venv/bin/python
.venv/bin/python -m pip install -r apps/api/requirements.txt
export PYTHONPATH=apps/api
.venv/bin/python -m roundmind.serve
```

另一个终端执行 `npm run dev`，访问 http://localhost:5173 。Vite 开发代理将 /api 转发到本地后端。OpenAPI 文档：http://127.0.0.1:8765/docs 。

Windows 桌面开发需要 Rust stable、MSVC C++ Build Tools 与 WebView2，先启动后端，再执行 `npm run desktop:dev`。当前桌面壳不会自动启动后端；正式分发的 sidecar、会话令牌和安装包属于后续工作。生产桌面 API 通信尚未接入，不应当作可发布版本。

## 验证

```bash
npm test
npm run build
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests
```

Windows 启动和测试的完整命令见 [INF-02 运维说明](docs/INF-02-operations.md)。PowerShell 测试时先执行 `$env:PYTHONPATH="apps/api"`，再运行 `.venv\Scripts\python.exe -m pytest apps/api/tests`。

CI 验证 Web、Python 与 Windows Tauri 壳编译；本地未执行的 CI 不能视为已经通过。

当前接口契约见 [INF-02 契约](docs/INF-02-contract.md)；健康检查增加 database 状态（200/503），JSON schema 见 [health-response.schema.json](docs/health-response.schema.json)。旧 INF-01 文档作为历史记录保留。本轮没有接入回放，因此回放同步与事件跳转检查不适用。

数据库迁移命令、日志字段、诊断导出、备份与恢复步骤见 [INF-02 运维说明](docs/INF-02-operations.md)。

枪法与逐枪契约见 [aim-alpha-contract.md](docs/aim-alpha-contract.md)。选择 Demo 库 → 导入 .dem → 等待解析 → 打开玩家报告 → 展开每一枪 → 定位回合证据。最大 1 GiB；只接受原始 CS2 Demo，不支持压缩包。导入副本保存在本机数据目录 imports；原始用户文件不删除。

当前没有用户授权的真实 Demo 样本，真实指标准确性尚未完成黄金回归。使用 `ROUNDMIND_GOLDEN_DEMO` 指向授权文件后运行测试；可选 `ROUNDMIND_GOLDEN_BASELINE` 指向人工核对的 JSON：`{"players":{"SteamID":{"shots":123,"kills":10}}}`。不设置时黄金用例明确跳过，合成事件测试不等于真实 Demo 验收。

浏览器回归：先激活 Python 虚拟环境，执行 `npm run test:e2e -w apps/web`。配置会启动独立临时数据目录的本地API与Vite；默认可复用已有开发服务。已有系统 Chromium 时设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium`，否则先 `npx playwright install chromium`。报告截图使用明确标注的合成夹具，不是真实比赛。CI新增独立browser job。

下一步：使用真实授权 Demo 与人工基线校准逐枪指标，并参考完美平台截图核实所需分析项。


解析排队或进行中可点击“取消任务”；取消不会删除导入副本，已取消任务可“重新解析”。重试保留job_id并递增attempt，旧执行不能覆盖新结果。保存报告的最终事务阶段不强制中断。接口、状态与验收见 [PAR-04 契约](docs/PAR-04-contract.md)。
