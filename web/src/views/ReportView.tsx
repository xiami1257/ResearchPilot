import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';

import { fetchSnapshot } from '../api';
import { linkCitations, splitReport } from '../reportMd';
import type { SessionDetail } from '../types';

interface Props {
  runId: string;
  onBack: (runId: string) => void; // 回到看板(任务未完成时)
  onHome: () => void;
}

export function ReportView({ runId, onBack, onHome }: Props) {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let closed = false;
    setLoading(true);
    fetchSnapshot(runId)
      .then((snap) => {
        if (!closed) {
          setSession(snap.session);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!closed) {
          setLoading(false);
          setSession(null);
        }
      });
    return () => {
      closed = true;
    };
  }, [runId]);

  if (loading) return <p className="hint">加载报告…</p>;
  if (!session) {
    return (
      <div className="empty">
        <p>报告不存在或已被清理。</p>
        <button className="btn-ghost" onClick={onHome}>返回首页</button>
      </div>
    );
  }

  // 未完成的任务 -> 引导回看板(用户可能是从历史列表点进来的)
  if (session.status === 'running') {
    return (
      <div className="empty">
        <p>任务还在进行中,报告尚未生成。</p>
        <button className="btn-primary" onClick={() => onBack(runId)}>回到实时看板</button>
      </div>
    );
  }
  if (session.status === 'failed') {
    return (
      <div className="empty">
        <p className="error">任务失败:{session.error}</p>
        <button className="btn-ghost" onClick={() => onBack(runId)}>查看失败详情</button>
        <button className="btn-ghost" onClick={onHome}>返回首页</button>
      </div>
    );
  }

  const md = session.report_md ?? '';
  const { body, citations } = splitReport(md);

  async function copyMd() {
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 剪贴板权限被拒时静默 —— 用户仍可手动全选复制 */
    }
  }

  return (
    <article className="report">
      <div className="report-head">
        <h1>{session.topic}</h1>
        <div className="report-actions">
          <button className="btn-ghost" onClick={onHome}>新建研究</button>
          <button className="btn-ghost" onClick={copyMd}>
            {copied ? '已复制 ✓' : '复制 Markdown'}
          </button>
        </div>
      </div>

      <div className="report-layout">
        <div className="report-body markdown">
          {/* a 的 href 以 #cite- 开头 => 上标引用,点击跳到脚注卡片 */}
          <ReactMarkdown
            components={{
              a: ({ href, children }) =>
                href?.startsWith('#cite') ? (
                  <sup className="cite">
                    <a href={href}>{children}</a>
                  </sup>
                ) : (
                  <a href={href} target="_blank" rel="noreferrer">
                    {children}
                  </a>
                ),
            }}
          >
            {linkCitations(body)}
          </ReactMarkdown>
        </div>

        <aside className="refs">
          <h2>引用来源({citations.length})</h2>
          {citations.length === 0 ? (
            <p className="hint">本篇报告没有通过核验的引用 —— 证据不足已如实标注。</p>
          ) : (
            <ol className="ref-list">
              {citations.map((c) => (
                <li key={c.no} id={`cite-${c.no}`} className="ref-item">
                  <a href={c.url} target="_blank" rel="noreferrer">
                    <span className="ref-title">{c.title || c.url}</span>
                    <span className="ref-host">{hostOf(c.url)}</span>
                  </a>
                </li>
              ))}
            </ol>
          )}
        </aside>
      </div>
    </article>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
