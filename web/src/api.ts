/**
 * 后端 API 封装(全部相对路径,dev 由 vite 代理,生产同源托管)。
 *
 * 时序约定(与后端 _event_stream 对应):
 *   页面打开 -> GET 快照(已发生事件) -> 开 SSE 等增量
 *   刷新/断线 = 重新快照 + 增量,天然不丢进度。
 */

import type { AnyEvent, SessionSnapshot, SessionSummary } from './types';

const BASE = '/api';

async function check(resp: Response): Promise<any> {
  if (!resp.ok) {
    const body = await resp.text().catch(() => '');
    throw new Error(`请求失败 ${resp.status}: ${body || resp.statusText}`);
  }
  return resp.json();
}

export async function createSession(topic: string, nSub: number): Promise<string> {
  const resp = await fetch(`${BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, n_sub: nSub }),
  });
  const body = await check(resp);
  return body.run_id as string;
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const body = await check(await fetch(`${BASE}/sessions`));
  return body.sessions as SessionSummary[];
}

export async function fetchSnapshot(runId: string): Promise<SessionSnapshot> {
  return (await check(await fetch(`${BASE}/sessions/${runId}`))) as SessionSnapshot;
}

/**
 * 订阅 SSE 增量事件流。
 * @param onEvent 每条事件回调
 * @param onClose 流结束(后端主动关闭:任务已终态/不存在)
 * @returns 手动关闭函数(组件卸载/换任务时必须调用)
 *
 * 注意:EventSource 断线会自动重连,所以"网络抖动"不用处理;
 * 只有流被后端关闭(终态)或手动 close 才停止。
 */
export function subscribeEvents(
  runId: string,
  onEvent: (ev: AnyEvent) => void,
  onClose: () => void,
): () => void {
  const es = new EventSource(`${BASE}/sessions/${runId}/events`);
  es.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data) as AnyEvent);
    } catch {
      /* 忽略坏帧 —— 宁可丢一条事件也不让整个看板崩 */
    }
  };
  es.onerror = () => {
    // readyState 为 CLOSED 才是后端关闭;CONNECTING 期间报错是正常重连
    if (es.readyState === EventSource.CLOSED) {
      onClose();
      es.close();
    }
  };
  return () => es.close();
}
