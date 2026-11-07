# 枪法 / 逐枪复盘 Alpha 交付记录

按用户最新方向：先打通“导入 Demo → 自动计算枪法事实 → 报告 → 每一枪单独展开 → 回合 Tick 证据”，参考完美世界竞技平台的逐枪分析思路；其最新版页面与指标未核实，不宣称同款或算法一致。

## 实现

- `apps/api/roundmind/imports.py`：1 GiB 内流式导入、扩展名/文件头双校验、SHA-256去重、异步任务、失败重试、中断恢复、300秒解析超时、任务/报告缓存、SQLite回合/事件索引、逐枪/事件分页。拒绝不受信任Origin的写请求。
- `parser.py`、`parse_worker.py`：demoparser2 0.42.1独立子进程；读取开火、伤害、死亡、弹着点和回合事实。可选速度/姿态/视角字段失败时降级，不补假数据。确认该版本提供Python3.12的Linux/Windows x64官方wheel。
- `aim.py`：可确认非热身完整回合的枪械开火、原始伤害、击杀、已知头部状态的爆头击杀占比、移动开火样本、按武器分组。队伤和未知阵营伤害不计；缺阵营的已知玩家开火仍保留并标记。未知速度/头部状态/参与快照保持未知。
- `apps/web/src/AimWorkspace.tsx`：导入、进度、去重提示、失败/重试、玩家报告、武器统计、质量口径、回合事件与Tick证据。
- `ShotLedger.tsx`：**每次已解析开火单独一条**，按回合筛选，分页继续加载至最后一枪；逐枪展开速度、姿态、视角、同Tick伤害/伤害部位和弹着点记录，跳到该枪原事件。不是只展示最差样本或整场平均分。
- `main.tsx`：入口接通，最近导入与文件数量来自API，无硬编码比赛结果。
- `tests/test_aim.py`、`test_imports.py`：纯计算、边界、索引、逐枪分页、多开火歧义、真实native进程损坏文件拒绝等。
- `apps/web/e2e`：真实API坏文件导入、明确标注的合成报告自动打开、逐枪展开与精确Tick跳转、390px布局；CI增加browser job，既有API与桌面检查保留。

接口与口径见 [aim-alpha-contract.md](aim-alpha-contract.md)，运行说明见 [README](../README.md)。本轮复用INF-02四张表，无新增DDL；任务/报告为本地JSON缓存，原始文件副本存imports，用户源文件不删除。

## 逐枪分析边界

每枪按weapon_fire事件分条；散弹一次开火不是每颗弹丸。仅提供已确认身份、非热身完整回合内的可解析事件，排除/缺失计数可见。

伤害与弹着点仅列为同Tick相关记录，未完成弹道归因。同Tick多次开火时不分配；无关联记录不叫空枪，有关联记录也不直接叫已确认命中。命中结论unknown，瞄准角度误差和真实反应时间null；尚未实现可见性、目标识别、完整弹道、版本武器精准规则、急停/压枪评分。移动阈值34u/s仅作观察，不当作精度惩罚阈值。

尚未有完美平台页面参考。需要逐枪页截图或录屏才能逐项核实其布局、指标与交互，不能靠名称猜测计算方法。

## 验证

- `PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q --junitxml=artifacts/aim-api-tests.xml`：**50 passed、1 skipped**，1项既有依赖弃用警告。
- skipped为真实黄金Demo回归：当前没有用户授权的真实.dem。合成事件测试和native坏文件测试不能证明真实枪法指标准确；没有声称黄金回归通过。
- `npm test`：4 passed。
- `npm run build`：TypeScript与Vite通过。
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run test:e2e -w apps/web`：2 passed。
- 浏览器报告与逐枪截图：`artifacts/aim-report-synthetic.png`，画面明确写“合成测试夹具 · 非真实比赛”。夹具仅被测试代码读取，不作为生产比赛填充。
- Linux本地验证；远程Windows CI未运行。真实Demo解析性能、跨版本准确性和全地图覆盖尚未验收。

## 后续验收输入

1. 用户有权使用的真实.dem（设置ROUNDMIND_GOLDEN_DEMO），以及可选的人工计数基线（ROUNDMIND_GOLDEN_BASELINE）。
2. 完美世界竞技平台逐枪分析截图或录屏，据此明确第一版直接实现、需重新计算、依赖额外数据的分项。

不接入3D、职业对标或云端AI；当前事件证据浏览不等于视频/完整地图回放。数据目录会保留导入副本和失败文件，未提供缓存清理/文件夹扫描/压缩包导入。正式桌面sidecar/会话鉴权、OpenAPI生成所有TS类型、完整任务取消和反馈闭环仍属后续任务。
