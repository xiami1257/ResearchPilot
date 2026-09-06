/**
 * 看板状态:由事件流推导(纯函数,便于理解与测试)。
 *
 * 设计:事件是"已发生事实",状态是"对事件的投影"。reducer 从快照事件
 * 全量重放得到初始状态,之后每条 SSE 增量再走同一个 reduce ——
 * 快照与增量共用一条代码路径,不会出现两种逻辑分叉。
 */

import type { AnyEvent, Role, Stage } from './types';

export interface LogItem {
  at: string;
  role: Role;
  agentId: number;
  message: string;
}

export interface SourceItem {
  subIndex: number;
  url: string;
  title: string;
}

export interface DashboardState {
  stage: Stage | null; // 最后收到的阶段推进;任务初始为 plan
  terminal: 'succeeded' | 'failed' | null;
  summary: string;
  error: string;
  logs: LogItem[];
  sources: SourceItem[]; // 事件顺序,最新在后
  notesDone: Record<number, number>; // sub_index -> 收录来源数
  noteLabels: Record<number, string>; // sub_index -> 子问题(来自 planner 消息,尽力而为)
}

export function initialState(stage: Stage | null): DashboardState {
  return {
    stage,
    terminal: null,
    summary: '',
    error: '',
    logs: [],
    sources: [],
    notesDone: {},
    noteLabels: {},
  };
}

/** 状态机的核心:一条事件 -> 状态变更(可变更新,配合不可变外层) */
export function reduceEvent(s: DashboardState, ev: AnyEvent): DashboardState {
  switch (ev.type) {
    case 'stage.changed':
      return { ...s, stage: ev.payload.stage };

    case 'agent.message':
      return {
        ...s,
        logs: [
          ...s.logs,
          { at: ev.at, role: ev.payload.role, agentId: ev.payload.agent_id, message: ev.payload.message },
        ],
      };

    // 注:events.py schema 里有 review.verdict,但编排器当前以一条
    // agent.message 汇报核验结论,不逐条发 —— 前端不实现死代码分支,
    // 收到也走 default 忽略。若将来要逐条展示,在这里加 case 即可。

    case 'source.found':
      return {
        ...s,
        sources: [...s.sources, { subIndex: ev.payload.sub_index, url: ev.payload.url, title: ev.payload.title }],
      };

    case 'note.ready':
      return {
        ...s,
        notesDone: { ...s.notesDone, [ev.payload.sub_index]: ev.payload.collected },
      };

    case 'task.succeeded':
      return { ...s, terminal: 'succeeded', summary: ev.payload.summary };

    case 'task.failed':
      return { ...s, terminal: 'failed', error: ev.payload.error };

    default:
      return s; // 未知事件类型(前后端版本错位):容忍,不崩
  }
}

/** 从事件数组重放得到状态(快照用);增量事件单独走 reduceEvent */
export function replay(events: AnyEvent[], stage: Stage | null): DashboardState {
  return events.reduce(reduceEvent, initialState(stage));
}

/** 当前所处的展示阶段(plan 恒为完成态起点,由 stage 反推) */
export function stageIndex(stage: Stage | null, terminal: 'succeeded' | 'failed' | null): number {
  if (terminal === 'succeeded' || terminal === 'failed') return 4; // 全部完成
  if (!stage) return 0;
  return { plan: 0, research: 1, review: 2, write: 3 }[stage];
}
