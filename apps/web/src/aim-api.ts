export type Demo = {id:string;filename:string;sha256:string;size:number;status:string};
export type Job = {job_id:string;demo_id:string;filename:string;status:string;error_code:string|null;attempt?:number;attempt_id?:string|null};
export type Round = {id:string;round_no:number;start_tick:number;end_tick:number};
export type Evidence = {round_id:string;round_no:number;start_tick:number;end_tick:number;event_id:string};
export type Finding = {finding_id:string;summary:string;observed_facts:string[];inferences:string[];counterfactual_options:string[];evidence_refs:Evidence[];confidence:null};
export type Player = {player_id:string;name:string;shots:number;damage:number;kills:number;headshot_kills:number;known_headshot_kills:number;unknown_headshot_kills:number;headshot_kill_ratio:number|null;damage_per_shot:number|null;moving_shot_ratio:number|null;speed_sample_count:number;moving_shots:number;speed_coverage:number|null;participated_rounds:number|null;coverage_complete:boolean;weapons:{weapon:string;shots:number;damage:number;kills:number}[];findings:Finding[]};
export type Report = {match_id:string;sha256:string;map:string;data_origin:string;parser_version:string;rule_version:string;movement_threshold:number;players:Player[];rounds:Round[];quality:Record<string,number>;limitations:string[]};
export type Event = {id:string;round_id:string;round_no:number;tick:number;type:string;actor:string;target:string|null;actor_name:string;target_name:string|null;weapon:string;speed:number|null;damage:number|null;headshot:boolean|null;hitgroup?:number|null};
export type EventPage = {items:Event[];next_tick:number|null;next_cursor:string|null};
const messages:Record<string,string>={invalid_demo:'文件不是有效的 CS2 Demo：文件头校验失败。',invalid_filename:'请选择 .dem 文件；暂不支持压缩包。',demo_too_large:'文件超过 1 GiB 限制。',unsupported_or_corrupt_demo:'解析失败：Demo 可能损坏或当前解析器尚不支持此版本。',no_confirmed_rounds:'未找到能确认非热身且完整结束的回合，未生成报告。',parse_timeout:'解析超过 300 秒，可重试或更换文件。',parser_process_failed:'解析进程异常退出，未生成报告。',interrupted:'上次解析被中断，可重新解析。',analysis_failed:'分析或保存失败，请检查本地磁盘空间。',report_not_ready:'报告尚未完成。',report_cache_missing:'报告缓存缺失，请检查本地数据目录。',job_not_retryable:'仅失败或已取消任务可重试。',job_not_cancelable:'任务已结束或正在保存报告，无法取消。'};
export function errorLabel(code:string|null){return code ? messages[code] || '任务未能完成，请重试。' : '';}
export async function api<T>(path:string, init?:RequestInit):Promise<T>{
 const response=await fetch('/api/v1'+path,init);
 const body=await response.json();
 if(!response.ok) throw new Error(errorLabel(body.error?.code) || '本地服务请求失败');
 return body.data as T;
}
export function importDemo(file:File,onProgress:(value:number)=>void):Promise<{job_id:string;demo_id:string;duplicate:boolean}>{
 return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();
  xhr.open('POST','/api/v1/demos/import');
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.setRequestHeader('X-Demo-Filename',encodeURIComponent(file.name));
  xhr.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded/event.total*100));};
  xhr.onload=()=>{try{const body=JSON.parse(xhr.responseText);if(xhr.status===202)resolve(body.data);else reject(new Error(errorLabel(body.error?.code)||'导入失败'));}catch{reject(new Error('本地服务返回了无效响应'));}};
  xhr.onerror=()=>reject(new Error('无法连接本地服务，文件未发送到云端。'));
  xhr.send(file);
 });
}
export type Shot=Event&{position:number[]|null;view_angles:number[]|null;is_airborne:boolean|null;ducked:boolean|null;correlation:string;same_tick_damage:number|null;damage_events:Event[];impact_events:Event[];moving_observation:boolean|null;hit_verdict:'unknown';limitations:string[]};
export type ShotPage={items:Shot[];next_tick:number|null;next_cursor:string|null};
