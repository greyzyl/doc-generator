import type { DocumentTemplate, OutputFile } from '../types/document';
import { MetadataForm } from './MetadataForm';
import { DownloadList } from './DownloadList';

interface WorkflowSidebarProps {
  collapsed: boolean;
  onCollapsedChange: (value: boolean) => void;
  apiBase: string;
  setApiBase: (value: string) => void;
  templates: DocumentTemplate[];
  selectedTemplateId: string;
  selectedTemplate: DocumentTemplate | null;
  onReloadTemplates: () => void;
  templatesLoading: boolean;
  onTemplateChange: (templateId: string) => void;
  documentName: string;
  setDocumentName: (value: string) => void;
  metadata: Record<string, string>;
  setMetadataField: (key: string, value: string) => void;
  file: File | null;
  setFile: (file: File | null) => void;
  draftId: string;
  fileId: string;
  parseId: string;
  canCreateDraft: boolean;
  canParse: boolean;
  canParseWithLLM: boolean;
  canSave: boolean;
  canGenerate: boolean;
  creatingDraft: boolean;
  parsing: boolean;
  parsingWithLLM: boolean;
  savingParagraphs: boolean;
  generating: boolean;
  onCreateDraft: () => void;
  onParseByRule: () => void;
  onParseByLLM: () => void;
  onSaveParagraphs: () => void;
  onGenerate: () => void;
  onUseSample: () => void;
  outputFiles: OutputFile[];
  getDownloadUrl: (file: OutputFile) => string;
}

export function WorkflowSidebar(props: WorkflowSidebarProps) {
  const templateSelector = (
    <section className="panel-block quick-block">
      <div className="panel-title-row compact">
        <h2>选择模板</h2>
        <button type="button" onClick={props.onReloadTemplates} disabled={props.templatesLoading} className="btn small secondary">
          {props.templatesLoading ? '加载中' : '重新加载'}
        </button>
      </div>

      <select value={props.selectedTemplateId} onChange={(event) => props.onTemplateChange(event.target.value)} className="input">
        <option value="">请选择模板</option>
        {props.templates.map((template) => (
          <option key={template.templateId} value={template.templateId} disabled={template.available === false}>
            {template.templateName}{template.available === false ? '（未配置）' : ''}
          </option>
        ))}
      </select>

      {props.selectedTemplate && (
        <p className="hint block-hint">
          {props.selectedTemplate.description || props.selectedTemplate.templateType} · {props.selectedTemplate.status || 'UNKNOWN'}
        </p>
      )}
    </section>
  );

  return (
    <aside className={`sidebar${props.collapsed ? ' is-collapsed' : ''}`}>
      <div className="sidebar-topbar">
        <div>
          <strong>工作栏</strong>
          <span>{props.collapsed ? '精简' : '专业'}</span>
        </div>
        <button
          type="button"
          onClick={() => props.onCollapsedChange(!props.collapsed)}
          aria-expanded={!props.collapsed}
          className="btn small secondary"
        >
          {props.collapsed ? '专业模式' : '精简模式'}
        </button>
      </div>

      {templateSelector}

      <section className="panel-block quick-block">
        <h2>上传正文</h2>
        <div className="form-list">
          <label className="field">
            <span className="field-label">正文文件</span>
            <input
              type="file"
              accept=".doc,.docx,.txt"
              onChange={(event) => props.setFile(event.target.files?.[0] || null)}
              className="input file-input"
            />
            {props.file && <span className="hint">已选择：{props.file.name}</span>}
          </label>

          <button type="button" onClick={props.onCreateDraft} disabled={!props.canCreateDraft || props.creatingDraft} className="btn primary full">
            {props.creatingDraft ? '创建中……' : '创建草稿并上传'}
          </button>
        </div>
      </section>

      <section className="panel-block quick-block">
        <h2>处理选项</h2>
        <div className="action-grid">
          <button type="button" onClick={props.onParseByRule} disabled={!props.canParse || props.parsing} className="btn blue">
            {props.parsing ? '解析中' : '规则解析'}
          </button>
          <button type="button" onClick={props.onParseByLLM} disabled={!props.canParseWithLLM || props.parsingWithLLM} className="btn purple">
            {props.parsingWithLLM ? '解析中' : 'LLM 解析'}
          </button>
          <button type="button" onClick={props.onSaveParagraphs} disabled={!props.canSave || props.savingParagraphs} className="btn green">
            {props.savingParagraphs ? '同步中' : '同步类型'}
          </button>
          <button type="button" onClick={props.onGenerate} disabled={!props.canGenerate || props.generating} className="btn rose">
            {props.generating ? '生成中' : '生成公文'}
          </button>
        </div>
      </section>

      <DownloadList files={props.outputFiles} getDownloadUrl={props.getDownloadUrl} />

      {!props.collapsed && (
        <div className="sidebar-details">
          <section className="panel-block">
            <label className="field">
              <span className="field-label">API Base</span>
              <input value={props.apiBase} onChange={(event) => props.setApiBase(event.target.value)} className="input" />
            </label>
          </section>

          <section className="panel-block">
            <h2>填写字段</h2>
            <div className="form-list">
              <label className="field">
                <span className="field-label">公文名称</span>
                <input value={props.documentName} onChange={(event) => props.setDocumentName(event.target.value)} className="input" />
              </label>

              <MetadataForm fields={props.selectedTemplate?.fields || []} metadata={props.metadata} onChange={props.setMetadataField} />
            </div>
          </section>

          <section className="panel-block">
            <h2>接口返回 ID</h2>
            <div className="id-list">
              <div>
                <b>draftId：</b>
                <span>{props.draftId || '未创建'}</span>
              </div>
              <div>
                <b>fileId：</b>
                <span>{props.fileId || '未上传'}</span>
              </div>
              <div>
                <b>parseId：</b>
                <span>{props.parseId || '未解析'}</span>
              </div>
            </div>
          </section>

          <button type="button" onClick={props.onUseSample} className="btn secondary full">
            使用示例 paragraphs 调试编辑区
          </button>
        </div>
      )}
    </aside>
  );
}
