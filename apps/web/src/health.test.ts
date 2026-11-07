import { afterEach, expect, it, vi } from 'vitest';
import { checkHealth } from './health';
afterEach(() => vi.unstubAllGlobals());
it('rejects invalid backend payload', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>({data:{status:'ok'}})}));
 await expect(checkHealth()).rejects.toThrow('接口响应不符合契约');
});
it('reports service failure', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:false}));
 await expect(checkHealth()).rejects.toThrow('服务连接失败');
});
it('accepts the INF-02 database-ready response', async () => {
 const body = {data:{status:'ok',service:'roundmind-api',database:{status:'ready',schema_revision:'0001_initial',expected_revision:'0001_initial'}},meta:{request_id:'test-request',version:'0.1.0'}};
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>body}));
 await expect(checkHealth()).resolves.toEqual(body);
});
it('rejects a service claiming success while database is unavailable', async () => {
 const body = {data:{status:'ok',service:'roundmind-api',database:{status:'unavailable',schema_revision:null,expected_revision:'0001_initial'}},meta:{request_id:'test-request',version:'0.1.0'}};
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>body}));
 await expect(checkHealth()).rejects.toThrow('接口响应不符合契约');
});
