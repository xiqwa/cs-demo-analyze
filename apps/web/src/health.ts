export type DatabaseHealth = {
  status: 'ready' | 'unavailable' | 'schema_mismatch';
  schema_revision: '0001_initial' | null;
  expected_revision: '0001_initial';
};
export type Health = {
  data: { status: 'ok' | 'degraded'; service: 'roundmind-api'; database: DatabaseHealth };
  meta: { request_id: string; version: '0.1.0' };
};
export async function checkHealth(): Promise<Health> {
  const response = await fetch('/api/v1/health', { signal: AbortSignal.timeout(4000) });
  if (!response.ok) throw new Error('服务连接失败');
  const body = await response.json();
  if (body.data?.status !== 'ok' || body.data?.service !== 'roundmind-api' ||
      body.data?.database?.status !== 'ready' || body.data?.database?.schema_revision !== '0001_initial' ||
      body.data?.database?.expected_revision !== '0001_initial' ||
      typeof body.meta?.request_id !== 'string' || body.meta?.version !== '0.1.0') {
    throw new Error('接口响应不符合契约');
  }
  return body;
}
