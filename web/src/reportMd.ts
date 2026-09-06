/**
 * 报告 markdown 的前端处理:
 *
 * 1. splitReport:把后端拼好的报告拆成「正文」+「引用来源」(render_references
 *    的产物是 "## 引用来源" 标题 + "[n] 标题 — url" 行,格式见 report.py)。
 *    正文交给 react-markdown 渲染,引用区渲染成可点击跳转的脚注卡片。
 *
 * 2. 上标化:把正文里的 [n] 改写成 [[n]](#cite-n) markdown 内部链接,
 *    点击即跳到文末对应脚注 —— 引用溯源从"可读"变成"可点"。
 *    简化处理:整段正则替换,不解析 markdown 语法边界;报告正文无代码块,
 *    该简化可接受(若未来报告含代码块,需换成 AST 级处理)。
 */

export interface Citation {
  no: number;
  title: string;
  url: string;
}

export interface SplitReport {
  body: string;
  citations: Citation[];
}

const REF_HEADING = '## 引用来源';
const CITATION_RE = /\[(\d+)\]/g;

export function splitReport(md: string): SplitReport {
  const lines = md.split('\n');
  const head = lines.findIndex((l) => l.trim() === REF_HEADING);
  if (head < 0) {
    // 防御:没有引用区(空池/旧数据),整篇当正文
    return { body: md, citations: [] };
  }
  const body = lines.slice(0, head).join('\n');
  const citations: Citation[] = [];
  for (const line of lines.slice(head + 1)) {
    const m = line.match(/^\s*\[(\d+)\]\s+(.*)$/);
    if (!m) continue;
    const rest = m[2];
    // 行格式:"标题 — url" 或只有 "url"(title 为空时)
    const urlMatch = rest.match(/(https?:\/\/\S+)$/);
    if (!urlMatch) continue;
    const url = urlMatch[1];
    let title = rest.slice(0, urlMatch.index).trim();
    title = title.replace(/[—-]\s*$/, '').trim();
    citations.push({ no: Number(m[1]), title, url });
  }
  return { body, citations };
}

/** 正文 [n] -> markdown 锚点链接,供 react-markdown 渲染成上标 */
export function linkCitations(body: string): string {
  return body.replace(CITATION_RE, '[[$1]](#cite-$1)');
}
