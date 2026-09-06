import { useEffect, useState } from 'react';

import { createSession, fetchSessions } from '../api';
import type { SessionSummary } from '../types';

/** 预置演示主题(面试/演示直接点,内容真实可讲;真机联调后再精选) */
const DEMO_TOPICS = [
  'MCP 协议为什么成为 AI Agent 的事实标准?',
  '大模型 RAG 系统的主流评测基准与短板',
  'AI 编程助手对软件工程师日常工作的实际影响',
];

interface Props {
  onStart: (runId: string) => void;
  onOpen: (runId: string) => void;
}

export function HomeView({ onStart, onOpen }: Props) {
  const [topic, setTopic] = useState('');
  const [nSub, setNSub] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<SessionSummary[]>([]);

  useEffect(() => {
    fetchSessions()
      .then(setHistory)
      .catch(() => setHistory([])); // 历史加载失败不阻塞主流程
  }, []);

  async function submit(t: string) {
    const text = t.trim();
    if (text.length < 2) {
      setError('主题太短了,多说几个字?');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const runId = await createSession(text, nSub);
      onStart(runId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建任务失败');
      setBusy(false);
    }
  }

  return (
    <div className="home">
      <header className="hero">
        <h1>输入一个主题,让 Agent 团队替你研究</h1>
        <p className="hero-sub">
          规划 · 并行检索 · 交叉核验 · 成稿 —— 全程可视化,每条结论都可点击溯源到真实网页
        </p>
      </header>

      <section className="create-card">
        <textarea
          className="topic-input"
          placeholder="例如:为什么 2025 年具身智能突然爆发?"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          rows={3}
          maxLength={300}
        />
        <div className="create-row">
          <label className="nsub">
            拆解深度
            <select value={nSub} onChange={(e) => setNSub(Number(e.target.value))}>
              <option value={3}>3 个子问题(快)</option>
              <option value={4}>4 个子问题(推荐)</option>
              <option value={5}>5 个子问题(深入)</option>
            </select>
          </label>
          <button className="btn-primary" disabled={busy} onClick={() => submit(topic)}>
            {busy ? '创建中…' : '开始研究'}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="demo-topics">
          {DEMO_TOPICS.map((t) => (
            <button key={t} className="chip" disabled={busy} onClick={() => submit(t)}>
              {t}
            </button>
          ))}
        </div>
      </section>

      {history.length > 0 && (
        <section className="history">
          <h2>历史报告</h2>
          <ul>
            {history.map((s) => (
              <li key={s.run_id}>
                <button className="history-row" onClick={() => onOpen(s.run_id)}>
                  <span className="history-topic">{s.topic}</span>
                  <span className={`badge status-${s.status}`}>{statusLabel(s)}</span>
                  <span className="history-time">{formatTime(s.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function statusLabel(s: SessionSummary): string {
  if (s.status === 'succeeded') return '已完成';
  if (s.status === 'failed') return '失败';
  return s.stage ? `进行中 · ${s.stage}` : '进行中';
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN');
}
