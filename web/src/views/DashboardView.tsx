import { useEffect, useRef, useState } from 'react';

import { fetchSnapshot, subscribeEvents } from '../api';
import { DashboardState, reduceEvent, replay, stageIndex } from '../dashboardState';
import { ROLE_LABEL, STAGES, type Role } from '../types';

interface Props {
  runId: string;
  onReport: () => void;
  onBack: () => void;
}

const ROLE_COLOR: Record<Role, string> = {
  planner: 'var(--role-planner)',
  researcher: 'var(--role-researcher)',
  reviewer: 'var(--role-reviewer)',
  writer: 'var(--role-writer)',
};

export function DashboardView({ runId, onReport, onBack }: Props) {
  const [state, setState] = useState<DashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    let closed = false;
    let unsubscribe: (() => void) | undefined;

    // 时序:先快照(重放全部事件),再挂 SSE 收增量 —— 刷新不丢进度
    fetchSnapshot(runId)
      .then((snap) => {
        if (closed) return;
        setState(replay(snap.events, snap.session.stage));
        setLoading(false);
        unsubscribe = subscribeEvents(
          runId,
          (ev) => {
            const prev = stateRef.current;
            if (prev) setState(reduceEvent(prev, ev));
          },
          // 流被后端关闭:任务已终态。若快照没追上终态(创建瞬间就完成),
          // 补一次快照刷新,保证「查看报告」按钮一定出现
          () => {
            if (closed) return;
            fetchSnapshot(runId).then((snap) => {
              if (!closed) setState(replay(snap.events, snap.session.stage));
            });
          },
        );
      })
      .catch(() => setLoading(false));

    return () => {
      closed = true;
      unsubscribe?.();
    };
  }, [runId]);

  const status = state ? (state.terminal === 'succeeded' ? 'done' : state.terminal === 'failed' ? 'failed' : 'running') : 'running';

  return (
    <div className="dash">
      <StageBar done={state ? stageIndex(state.stage, state.terminal) : 0} />

      {loading && <p className="hint">加载任务进度…</p>}
      {!loading && !state && <p className="hint">任务不存在或已被清理。</p>}

      {state && (
        <>
          <div className="dash-grid">
            <section className="panel log-panel">
              <h2>Agent 动态</h2>
              <LogFeed state={state} />
            </section>
            <aside className="panel source-panel">
              <h2>
                已采集来源 <span className="count">{state.sources.length}</span>
              </h2>
              <SourceGrid sources={state.sources} />
            </aside>
          </div>

          {status === 'running' && <RunningBar state={state} />}
          {status === 'done' && (
            <div className="banner banner-ok">
              <span>研究完成{state.summary ? `:${state.summary}` : ''}</span>
              <button className="btn-primary" onClick={onReport}>
                查看报告 →
              </button>
            </div>
          )}
          {status === 'failed' && (
            <div className="banner banner-err">
              <strong>研究失败</strong>
              <span>{state.error}</span>
              <button className="btn-ghost" onClick={onBack}>
                返回重试
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function StageBar({ done }: { done: number }) {
  return (
    <div className="stage-bar">
      {STAGES.map((s, i) => {
        const n = i + 1;
        const isDone = done >= n;
        const isActive = done === i;
        return (
          <div key={s} className={`stage ${isDone ? 'done' : ''} ${isActive ? 'active' : ''}`}>
            <span className="stage-dot">{isDone ? '✓' : n}</span>
            <span className="stage-name">{stageName(s)}</span>
          </div>
        );
      })}
    </div>
  );
}

function stageName(s: string): string {
  return { plan: '规划', research: '并行检索', review: '交叉核验', write: '撰写成稿' }[s] ?? s;
}

function LogFeed({ state }: { state: DashboardState }) {
  // 自动滚到底:新消息进来时容器贴底(用户上翻查看时不强拉)
  const ref = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  useEffect(() => {
    if (pinned && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [state.logs.length, pinned]);

  if (state.logs.length === 0) {
    return <p className="hint">Agent 还没开始干活…</p>;
  }
  return (
    <div
      className="log-feed"
      ref={ref}
      onScroll={(e) => {
        const el = e.currentTarget;
        setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
      }}
    >
      {state.logs.map((log, i) => (
        <div key={i} className="log-line">
          <span className="log-badge" style={{ background: ROLE_COLOR[log.role] }}>
            {ROLE_LABEL[log.role]}
            {log.role === 'researcher' ? `·${log.agentId + 1}` : ''}
          </span>
          <span className="log-msg">{log.message}</span>
          <span className="log-time">{formatTime(log.at)}</span>
        </div>
      ))}
    </div>
  );
}

function SourceGrid({ sources }: { sources: { subIndex: number; url: string; title: string }[] }) {
  if (sources.length === 0) return <p className="hint">检索命中的网页会陆续出现在这里…</p>;
  return (
    <ul className="source-grid">
      {sources.map((s, i) => {
        let host = '';
        try {
          host = new URL(s.url).host;
        } catch {
          /* 防御:坏 URL 只显示原文 */
        }
        return (
          <li key={i} className="source-card">
            <a href={s.url} target="_blank" rel="noreferrer">
              <span className="source-title">{s.title || s.url}</span>
              <span className="source-host">{host || s.url}</span>
            </a>
            <span className="source-sub">子问题 #{s.subIndex + 1}</span>
          </li>
        );
      })}
    </ul>
  );
}

function RunningBar({ state }: { state: DashboardState }) {
  const nDone = Object.keys(state.notesDone).length;
  return (
    <div className="running-bar">
      <span className="spinner" />
      {nDone > 0 ? `已完成 ${nDone} 个子问题笔记` : 'Agent 团队正在并行检索…'}
    </div>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('zh-CN', { hour12: false });
}
