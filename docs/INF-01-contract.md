# INF-01 接口契约（实现前定义）
GET /api/v1/health：无需令牌，200 返回 {data:{status:"ok",service:"roundmind-api"},meta:{request_id:string,version:"0.1.0"}}。
所有响应带 X-Request-ID（服务端生成 UUID）。未定义接口返回统一错误结构 error/code/message/details/retryable 和 request_id。
仅允许 localhost:5173、127.0.0.1:5173 和 Tauri 本地来源；服务仅绑定 127.0.0.1。
此任务不提供 Demo 导入、解析、回放、云端 AI 或训练数据。
