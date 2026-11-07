# PAR-04 任务生命周期契约

范围：在现有导入/解析队列上补齐取消、取消后重试和并发终态保护。不修改解析算法或生成模拟比赛。

- `POST /api/v1/jobs/{id}/cancel`：同现有写接口校验Origin。未知任务404；排队/解析中任务可取消，成功200返回 `{data:{job_id,status:"canceled"},meta}`；已取消可重复调用，仍返回200；已完成或失败任务409/job_not_cancelable。数据库事务保存阶段不强行中断，若保存已完成则409，避免半份成功报告。
- 取消队列任务后不得启动解析器；取消正在解析的任务会终止该任务的独立子进程。取消不删除导入副本、用户原文件；API不提供成功报告。取消返回后旧执行不能再把状态写成failed或complete。
- `POST /api/v1/jobs/{id}/retry`：允许failed/canceled，返回202；queued/parsing/indexing/complete返回409。每次重试生成新attempt_id，attempt计数递增，仍复用原job_id和SHA去重记录。即使旧执行尚在退出，旧执行也不得覆盖新attempt的状态或提交报告。
- 任务查询追加attempt（整数）、attempt_id（UUID字符串），状态以SQLite为准；JSON保存文件名与尝试信息。重启后处理中任务标记failed/interrupted，取消终态保持canceled。关闭服务终止正在运行的子进程并回收协调线程。
- 只允许当前attempt从queued→parsing→indexing→complete；异常转failed，用户取消转canceled。提交索引/报告和取消以同一服务锁串行化，先进入最终事务提交者胜出，不返回“已取消”后又产生成功结果。
- UI显示“已取消”与“重新解析”；队列/解析状态显示取消按钮，保存阶段不显示取消按钮。取消后停止轮询；重试后恢复轮询。不是取消尚未提交的文件传输。

验收先写：队列取消不启动、解析取消实际终止子进程、重复取消幂等、完成后取消冲突、Origin检查、取消后重试、旧执行不得覆盖新attempt、重启保持终态。测试使用受控事件/子进程，不依赖真实Demo来验证队列语义。
