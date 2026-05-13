import type { ParagraphBlock } from '../types/document';

interface JsonPreviewProps {
  parseId: string;
  paragraphs: ParagraphBlock[];
}

export function JsonPreview({ parseId, paragraphs }: JsonPreviewProps) {
  return (
    <aside className="panel json-panel">
      <div className="panel-title-row">
        <h2>提交给后端的 paragraphs</h2>
        <span className="pill muted">{paragraphs.length} 条</span>
      </div>
      <p className="hint">段落换行只存在于前端编辑区，提交时不会写入 text。</p>
      <pre className="json-preview">{JSON.stringify({ parseId, paragraphs }, null, 2)}</pre>
    </aside>
  );
}
