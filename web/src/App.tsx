import { useState } from 'react';

import { DashboardView } from './views/DashboardView';
import { HomeView } from './views/HomeView';
import { ReportView } from './views/ReportView';

/**
 * 视图导航(无路由库 —— 三视图 + 历史,状态机足够,避免多余依赖):
 *   home(输入/历史) -> 创建成功 -> dash(实时看板) -> 完成 -> report
 *   历史列表点开:已完成 -> report;进行中/失败 -> dash(可重放快照)
 */

type View =
  | { name: 'home' }
  | { name: 'dash'; runId: string }
  | { name: 'report'; runId: string };

export default function App() {
  const [view, setView] = useState<View>({ name: 'home' });

  return (
    <div className="app">
      <nav className="navbar">
        <button className="brand" onClick={() => setView({ name: 'home' })}>
          <span className="brand-mark">◈</span> ResearchPilot
        </button>
        {view.name !== 'home' && (
          <button className="btn-ghost" onClick={() => setView({ name: 'home' })}>
            ← 新建研究
          </button>
        )}
      </nav>
      <main className="main">
        {view.name === 'home' && (
          <HomeView
            onStart={(runId) => setView({ name: 'dash', runId })}
            onOpen={(runId) => setView({ name: 'report', runId })}
          />
        )}
        {view.name === 'dash' && (
          <DashboardView
            runId={view.runId}
            onReport={() => setView({ name: 'report', runId: view.runId })}
            onBack={() => setView({ name: 'home' })}
          />
        )}
        {view.name === 'report' && (
          <ReportView
            runId={view.runId}
            onBack={(runId) => setView({ name: 'dash', runId })}
            onHome={() => setView({ name: 'home' })}
          />
        )}
      </main>
      <footer className="footer">Planner → Researcher ×N → Reviewer → Writer · 引用全程可溯源</footer>
    </div>
  );
}
