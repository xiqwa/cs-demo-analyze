# 枪法复盘 Alpha 契约

范围：本轮按用户指定的纵向功能流合并推进 PAR-01/解析适配/个人分析/事件证据 UI；不声称复刻完美世界竞技平台，也不接入全地图3D、职业对标或云端AI。

## 输入和任务

POST /api/v1/demos/import：application/octet-stream 原始 .dem 字节，X-Demo-Filename 为 URI 编码文件名，最大 1 GiB；仅接受 PBDEMS2\0 文件头和 .dem 后缀，不解压。导入只发送给本机 localhost API，不上传云端。请求流式写入用户数据目录 imports，SHA-256 去重。返回 202 {data:{job_id,demo_id,duplicate},meta}；GET /api/v1/jobs/{id} 查询 queued/parsing/indexing/complete/failed/canceled，错误为稳定错误码。重试 POST /api/v1/jobs/{id}/retry。异步解析在独立 Python 子进程中运行，最多一个并行解析，单任务 300 秒超时；错误或进程退出不能生成成功报告。退出服务会终止子进程，下一启动把中断任务标记为 failed/interrupted。

GET /api/v1/demos 返回已导入列表（最多100，最新优先）；GET /api/v1/matches/{id}/aim 返回枪法报告；GET /api/v1/rounds/{id}/events?from_tick=&to_tick=&limit= 返回最多500条、按Tick排序的证据事件，响应带next_tick/next_cursor用于同Tick事件继续分页。未知ID404；未完成报告409。所有新增响应使用现有信封，不暴露本机路径/原始解析器错误。

导入/重试拒绝非白名单 Origin（防止其他网站提交本机任务）；CORS 允许本机开发和Tauri来源。无Origin请求供本机命令行使用。后端仍只绑定127.0.0.1；尚不是有会话鉴权的正式桌面发布版。

## 统计口径 aim-events-v1

- 解析器固定 demoparser2 0.42.1；仅读取Demo事实。完成的非热身回合由 round_freeze_end 到 round_end（含结束Tick）界定；无法确认热身状态时不混入统计。回合号为文件内已确认完成回合的顺序，界面称“记录回合”，不保证等于比赛官方回合号。缺失/未完成回合排除并显示质量警告。
- 枪械白名单明确列出，刀/道具/C4/电击枪不算枪械。开火事实即使缺阵营仍保留，但会标注质量缺失；伤害/击杀只计双方阵营可知（2/3）且不同、玩家身份有效的事件；队伤、自杀和未知阵营不计，排除数量可见。无头像/语音/心理推断。
- 开火次数＝weapon_fire事件数；枪械伤害＝player_hurt的dmg_health原始记录和（可能含过量伤害），不称有效HP伤害或ADR；枪械击杀＝player_death计数；爆头击杀占比＝可确认头部状态的枪械爆头击杀/可确认头部状态的枪械击杀，报告分母与未知状态数量，0分母返回null。
- 每枪记录伤害＝枪械伤害/开火次数，仅在身份和阵营字段完整时计算；它不是命中率。穿透、散弹和事件粒度使“伤害事件/子弹数”不能当作命中率。
- 移动开火比例＝水平速度sqrt(vx²+vy²)>34 u/s的枪械开火样本/有完整速度数据的枪械开火样本。阈值只是版本化观察规则，不是武器精准阈值，不证明急停失败。缺速度不当静止、不插值，样本覆盖率可见。
- 回合参与次数来自冻结结束Tick的team_num快照；缺参与快照时不猜ADR或参战回合。无反应时间、首发命中率、瞄准角度或枪法总评分。

报告记录parser_version、rule_version、Demo哈希、真实数据来源、排除计数、缺失字段和每项指标样本量。移动开火候选每玩家每回合保留一条最高速样本，含事实、假设、替代建议、证据round_id/Tick、未校准confidence=null与反馈状态。不把该候选当作已证实的错误。

证据页提供真实事件列表、记录回合选择、Tick范围筛选与跳转高亮，不宣称视频/地图回放。API按范围分页读取SQLite事件，不把整场逐Tick数据发往UI。

## 存储和验证

复用INF-02四张表，无额外DDL；任务JSON与报告缓存在用户目录jobs/reports，原始导入副本在imports。复制不删除用户源文件。工作缓存原子替换，SQLite事务索引；只有DB状态complete且报告存在才允许展示成功报告。坏文件/失败/重试/哈希重复要可验证。

测试使用显式标注的合成事件夹具，仅用于算法与边界测试，不包装成真实比赛。真实黄金测试由 ROUNDMIND_GOLDEN_DEMO 指定用户授权.dem，并可指定人工核对的基线JSON；没有文件时明确skip，不能因此声称解析准确率已验证。


## 逐枪明细（按用户最新要求新增）

GET /api/v1/matches/{id}/shots?player_id=&round_id=&from_tick=&cursor=&limit=：按开火事件逐条分页，默认50、最多200，可继续读取到最后一枪，报告总分不是替代项。仍只分析有可用身份的枪械开火、已确认非热身完整回合；身份缺失和被排除回合计数可见，不能声称整个任意Demo每个字节都完整还原。

每条记录包含枪械、Tick、记录回合、水平速度、可用的位置/视角/腾空/蹲伏数据，及可定位原事件的ID。字段缺失为null，不自动补齐。逐枪阈值规则shot-evidence-v1，仅描述观察事实。

关联规则：仅关联同玩家、同回合、同Tick的同武器敌方伤害事件；弹着点也仅按同Tick列为相关记录。同Tick存在多次开火则correlation=ambiguous_multiple_fires，不强行分配伤害或弹着点。否则correlation=same_tick_only。same_tick_damage只有确实存在候选伤害事件时才是数值，无候选时null。它不是已验证的弹道归因，不把无记录标为空枪，也不把相关记录直接认定命中。

hit_verdict固定unknown；aim_error_degrees/reaction_time_ms为null。尚无精确弹道、敌人可见性、目标识别和武器/版本精度校准，因此不能生成瞄准偏差、真实反应时间、首发命中、压枪/急停评分。后续需要用户提供完美平台逐枪页面截图或录屏，才能核实并对齐具体分项；不声称现阶段与其指标相同。

新增bullet_impact事实事件，x/y/z作为世界坐标；同Tick事件按ID稳定排序，不推断子Tick先后。散弹按一次weapon_fire记录，不把一次开火当作每颗弹丸。证据页为事件浏览，非完整弹道模拟。


任务取消/重试与attempt并发保护已在PAR-04补齐，详见 [PAR-04-contract.md](PAR-04-contract.md)。排队与解析可取消，最终保存事务不中途强制中断。
