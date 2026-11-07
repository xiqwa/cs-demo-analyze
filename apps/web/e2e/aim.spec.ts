import {test,expect} from '@playwright/test';
import fixture from './fixtures/aim.json' with {type:'json'};

test('real API rejects a corrupt upload without presenting a report',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'进入 Demo 库'}).click();
 await page.locator('input[type=file]').setInputFiles({name:'deliberately-corrupt-test.dem',mimeType:'application/octet-stream',buffer:Buffer.concat([Buffer.from('PBDEMS2\0'),Buffer.alloc(64)])});
 await expect(page.getByRole('status')).toContainText('解析失败',{timeout:20000});
 await expect(page.getByRole('status').getByRole('button',{name:'重新解析'})).toBeVisible();
 await expect(page.getByText('每一枪，都能回到现场核对。')).toHaveCount(0);
});

test('explicit synthetic report locates the exact event and supports mobile',async({page})=>{
 const reply=(data:unknown)=>({contentType:'application/json',body:JSON.stringify({data,meta:{request_id:'fixture',version:'0.1.0'}})});
 await page.route('**/api/v1/demos',route=>route.fulfill(reply({items:[{id:fixture.report.match_id,filename:'合成测试夹具.dem',sha256:'a'.repeat(64),size:100,status:'complete'}]})));
 await page.route('**/api/v1/matches/*/aim',route=>route.fulfill(reply(fixture.report)));
 await page.route('**/api/v1/matches/*/shots*',route=>route.fulfill(reply({items:fixture.events.filter(e=>e.type==='weapon_fire').map(e=>({...e,correlation:'same_tick_only',same_tick_damage:e.tick===120?80:null,damage_events:fixture.events.filter(d=>d.type==='player_hurt'&&d.tick===e.tick),impact_events:[],moving_observation:e.speed===null?null:e.speed>34,hit_verdict:'unknown',limitations:[]})),next_tick:null,next_cursor:null})));

 await page.route('**/api/v1/demos/import',route=>route.fulfill({status:202,...reply({job_id:fixture.report.match_id,demo_id:fixture.report.match_id,duplicate:false})}));
 let polls=0;
 await page.route('**/api/v1/jobs/*',route=>route.fulfill(reply({job_id:fixture.report.match_id,demo_id:fixture.report.match_id,filename:'合成测试夹具.dem',status:polls++===0?'queued':'complete',error_code:null})));
 await page.route('**/api/v1/rounds/*/events*',route=>{
  const url=new URL(route.request().url());const tick=Number(url.searchParams.get('from_tick'));
  return route.fulfill(reply({items:fixture.events.filter(e=>e.tick>=tick),next_tick:null,next_cursor:null}));
 });
 await page.goto('/');
 await page.getByRole('button',{name:'进入 Demo 库'}).click();
 await page.locator('input[type=file]').setInputFiles({name:'合成测试夹具.dem',mimeType:'application/octet-stream',buffer:Buffer.from('explicit-browser-test-fixture')});
 await expect(page.getByText('合成测试夹具 · 非真实比赛')).toBeVisible();
 await expect(page.getByText('移动开火占比',{exact:true})).toBeVisible();
 await expect(page.getByText('50.0%',{exact:true})).toBeVisible();
 await expect(page.getByRole('region',{name:'逐枪分析'})).toBeVisible();
 await expect(page.locator('.shot-row')).toHaveCount(3);
 await page.locator('.shot-row').nth(1).click();
 await expect(page.locator('.shot-detail')).toContainText('移动状态数据缺失，不能判断是否停稳');
 await page.locator('.shot-row').first().click();
 await expect(page.locator('.shot-detail')).toContainText('是否影响精度需要结合武器');
 await page.getByRole('button',{name:'查看这一枪的回合证据'}).click();
 await expect(page.getByTestId('evidence-tick')).toHaveText('120');
 await expect(page.locator('.aim-event.highlight')).toHaveCount(1);
 await expect(page.locator('.aim-event.highlight')).toContainText('40.0 u/s');
 await page.screenshot({path:'../../artifacts/aim-report-synthetic.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('synthetic task can be canceled and retried without stale status',async({page})=>{
 const id='synthetic-task-lifecycle';
 let status='parsing',attempt=1,imported=false;
 const reply=(data:unknown)=>({contentType:'application/json',body:JSON.stringify({data,meta:{request_id:'fixture',version:'0.1.0'}})});
 await page.route('**/api/v1/demos',route=>route.fulfill(reply({items:imported?[{id,filename:'合成任务状态测试.dem',sha256:'a'.repeat(64),size:100,status}]:[]})));
 await page.route('**/api/v1/demos/import',route=>{imported=true;return route.fulfill({status:202,...reply({job_id:id,demo_id:id,duplicate:false})});});
 await page.route('**/api/v1/jobs/'+id,route=>route.fulfill(reply({job_id:id,demo_id:id,filename:'合成任务状态测试.dem',status,attempt,attempt_id:'fixture-'+attempt,error_code:null})));
 await page.route('**/api/v1/jobs/'+id+'/cancel',route=>{status='canceled';return route.fulfill(reply({job_id:id,status}));});
 await page.route('**/api/v1/jobs/'+id+'/retry',route=>{status='parsing';attempt++;return route.fulfill({status:202,...reply({job_id:id})});});
 await page.goto('/');
 await page.getByRole('button',{name:'进入 Demo 库'}).click();
 await page.locator('input[type=file]').setInputFiles({name:'合成任务状态测试.dem',mimeType:'application/octet-stream',buffer:Buffer.from('explicit-synthetic-task-fixture')});
 const task=page.getByRole('status');
 await expect(task).toContainText('正在解析');
 await task.getByRole('button',{name:'取消任务',exact:true}).click();
 await expect(task).toContainText('已取消');
 await expect(task.getByRole('button',{name:'取消任务',exact:true})).toHaveCount(0);
 await expect(task).toContainText('导入副本仍保留');
 await page.screenshot({path:'../../artifacts/PAR-04-canceled-synthetic.png',fullPage:true});
 await task.getByRole('button',{name:'重新解析',exact:true}).click();
 await expect(task).toContainText('第 2 次尝试');
 await expect(task.getByRole('button',{name:'取消任务',exact:true})).toBeVisible();
});
