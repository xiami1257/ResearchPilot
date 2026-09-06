/**
 * 后端契约类型 —— 与 src/researchpilot/core/events.py(唯一事实来源)对齐。
 *
 * 事件采用"判别联合"(discriminated union):type 字段决定 payload 结构。
 * 好处:渲染时 switch(ev.type) 后 TS 自动把 payload 收窄成对应类型,
 * 不会出现"取错字段静默 undefined"的前端 bug。
 */

export type Stage = 'plan' | 'research' | 'review' | 'write';
export type Role = 'planner' | 'researcher' | 'reviewer' | 'writer';
export type RunStatus = 'running' | 'succeeded' | 'failed';

/** 历史列表项(GET /api/sessions,不含报告全文/错误) */
export interface SessionSummary {
  run_id: string;
  topic: string;
  status: RunStatus;
  stage: Stage | null;
  created_at: string;
}

/** 会话详情(GET /api/sessions/{id},含全量字段) */
export interface SessionDetail extends SessionSummary {
  error: string | null;
  report_md: string | null;
}

// ---------------------------------------------------------------------------
// 事件信封(SSE 与快照共用同一结构)
// ---------------------------------------------------------------------------

interface Base {
  run_id: string;
  at: string;
}

export type AnyEvent =
  | (Base & { type: 'stage.changed'; payload: { stage: Stage } })
  | (Base & {
      type: 'agent.message';
      payload: { role: Role; agent_id: number; message: string };
    })
  | (Base & {
      type: 'source.found';
      payload: {
        agent_id: number;
        sub_index: number;
        query: string;
        url: string;
        title: string;
        snippet?: string;
      };
    })
  | (Base & {
      type: 'note.ready';
      payload: { agent_id: number; sub_index: number; collected: number };
    })
  | (Base & {
      type: 'review.verdict';
      payload: {
        agent_id: number;
        sub_index: number;
        verdict: 'supported' | 'unsupported' | 'unverifiable';
        reason: string;
      };
    })
  | (Base & { type: 'task.succeeded'; payload: { summary: string } })
  | (Base & { type: 'task.failed'; payload: { error: string } });

/** 会话详情的快照响应 */
export interface SessionSnapshot {
  session: SessionDetail;
  events: AnyEvent[];
}

export const STAGES: Stage[] = ['plan', 'research', 'review', 'write'];

/** 各 Agent 角色的人类可读名(看板徽标/日志配色用) */
export const ROLE_LABEL: Record<Role, string> = {
  planner: '规划',
  researcher: '检索',
  reviewer: '核验',
  writer: '写作',
};
