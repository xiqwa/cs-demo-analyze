# PAR-04 交付记录

本轮只处理一个任务ID：PAR-04，补齐已有队列的取消/重试/失败恢复，不修改逐枪计算方法。

变更文件：
- apps/api/roundmind/imports.py：ParseAttempt、每次尝试唯一ID、Future取消、独立子进程终止、旧执行隔离、SQLite为准的任务查询、关闭时回收子进程和中断队列。
- apps/api/roundmind/logging.py：允许记录cancel路由模板，仍不记录实际任务URL或敏感路径。
- apps/web/src/AimWorkspace.tsx、aim-api.ts、aim.css、main.tsx：取消按钮、已取消终态、重试、尝试次数、停止终态轮询和防重复操作。逐枪报告/证据导航保留。
- apps/api/tests/test_jobs.py：7项生命周期/并发测试；test_imports.py仅适配内部解析器测试替身的attempt参数。
- apps/web/e2e/aim.spec.ts：增加明确标注的合成任务取消→重试UI测试；CI增加该截图产物。
- README.md、aim-alpha-contract.md及本任务契约/交付记录。

接口影响：新增POST /api/v1/jobs/{id}/cancel；重试从仅failed扩展到failed/canceled；查询增加attempt/attempt_id。取消幂等，未知ID404，终态冲突409，不受信任Origin403。无数据库DDL。

事务语义：保存索引与报告的最后阶段不可抢占，使用服务锁与取消串行化；取消先胜出则旧执行不能提交，完成先胜出则取消返回409。不出现200已取消之后又由旧执行改成成功。每次尝试使用独立临时输出名，立即重试不会读到旧输出。

测试：
- `PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q --junitxml=artifacts/PAR-04-api-tests.xml`：57 passed、1 skipped；既有依赖弃用警告1项。skip为未提供真实授权Demo的黄金解析回归。
- `npm test`：4 passed。
- `npm run build`：TypeScript检查与Vite构建通过。
- 激活本地Python虚拟环境后，`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run test:e2e -w apps/web`：3 passed。浏览器验证取消、重试、原有坏文件处理、逐枪展开与证据Tick跳转。
- 七项新测试覆盖：排队取消不启动/幂等；取消后立即重试及迟到成功结果隔离；终止真实受控Python子进程；Origin/未知ID；重启后取消终态与attempt计数；最终提交与取消竞争；关闭时杀进程并持久化队列中断。

截图：artifacts/PAR-04-canceled-synthetic.png（明确为合成任务状态测试，无真实比赛或枪法结果）。JUnit：artifacts/PAR-04-api-tests.xml。

已知限制：只支持单服务进程/单解析worker。不是文件传输取消，也不删除输入文件。保存事务阶段可能先完成，取消此时返回冲突。Windows CI已配置，未在本机运行。真实Demo准确性/跨版本/性能校准仍缺有效授权样本；本轮没有修改解析算法，不把生命周期测试视为黄金Demo回归通过。

下一任务：PAR-02/03真实Demo与人工基线验收，补字段/坐标兼容矩阵；有真实数据后继续逐枪归因与可视化，不提前生成未经校准的命中/急停/瞄准评分。
