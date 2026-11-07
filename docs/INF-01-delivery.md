# INF-01 本轮交付记录

变更：根 package.json/package-lock.json 建立 workspace；apps/web 提供 React/TypeScript 工作台、空状态及健康检查；apps/api 提供 FastAPI 服务与契约测试；apps/desktop 提供 Tauri 2 壳；.github/workflows/ci.yml 提供 Web/API 检查与 Windows 壳编译任务。

接口影响：新增 GET /api/v1/health，响应及错误结构见 INF-01-contract.md；自动生成 /openapi.json 与 /docs。没有 Demo 数据接口，没有文件读取、上传或云端 AI。

验证结果：
- `npm test`：2 passed。
- `npm run build`：TypeScript 检查与 Vite 构建成功。
- `PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests`：4 passed，1 项依赖弃用警告。
- 启动 Uvicorn 和 Vite 后，curl http://127.0.0.1:5173/api/v1/health 返回正常，通过 Vite 代理完成前后端联通。

已知限制：本机缺少 cargo，未验证 Tauri 编译或 Windows 安装。Windows CI 尚未运行。Playwright Chromium 下载被网络策略拒绝（cdn.playwright.dev 返回 403 Domain forbidden），随后使用系统 /usr/bin/chromium 完成浏览器验证：健康状态显示、Demo 库往返导航、390px 窄屏无横向溢出均通过；截图见 dashboard.png。当前桌面只提供开发壳，后端须独立启动；生产 API 连接、sidecar 生命周期、令牌鉴权与安装打包待后续实现。Vite 仅用于开发，不应暴露为生产服务。

数据：界面只有真实空状态，没有 Mock 比分、坐标或报告。无回放模块，因此本轮无同步与事件跳转可验。

下一任务：INF-02（数据库/迁移/日志），按文档继续先定义契约与测试再实现。
