import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiClient } from './api/client';
import { DocumentApi } from './api/documentApi';
import { CharacterEditor } from './components/CharacterEditor';
import { StepBadge } from './components/StepBadge';
import { WorkflowSidebar } from './components/WorkflowSidebar';
import { DEFAULT_API_BASE, DEFAULT_PARAGRAPH_TYPES, FALLBACK_TEMPLATES, SAMPLE_PARAGRAPHS } from './constants/defaults';
import type { CharUnit, DocumentTemplate, OutputFile, ParagraphBlock, ParagraphTypeOption } from './types/document';
import { charUnitsToParagraphs, createTypeLabelMap, paragraphsToCharUnits } from './utils/paragraphBlocks';
import { clearBrowserSelection } from './utils/selection';
import './styles.css';

const DEFAULT_TEMPLATE_ID = 'LETTER';

const DEFAULT_METADATA: Record<string, string> = {
  issuingOrg: '中铁二十四局集团有限公司',
  docNumber: '中铁二十四局',
  securityLevel: 'NONE',
  mainRecipient: '中铁二十四局',
  printOrg: '中铁二十四局',
  ccRecipients: '中铁二十四局',
  issuer: '朱映琏',
  printDate: '2026-05-09',
};

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const api = useMemo(() => new DocumentApi(new ApiClient(apiBase)), [apiBase]);

  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [paragraphTypes, setParagraphTypes] = useState<ParagraphTypeOption[]>(DEFAULT_PARAGRAPH_TYPES);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [documentName, setDocumentName] = useState('正文模板格式确认样例');
  const [metadata, setMetadata] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);

  const [draftId, setDraftId] = useState('');
  const [fileId, setFileId] = useState('');
  const [parseId, setParseId] = useState('');

  const [charUnits, setCharUnitsState] = useState<CharUnit[]>([]);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState('先加载模板，填写字段并上传正文文件。也可以直接用示例数据测试字符级标注。');

  const [creatingDraft, setCreatingDraft] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [parsingWithLLM, setParsingWithLLM] = useState(false);
  const [savingParagraphs, setSavingParagraphs] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [outputFiles, setOutputFiles] = useState<OutputFile[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);

  const typeLabelMap = useMemo(() => createTypeLabelMap(paragraphTypes), [paragraphTypes]);
  const selectedTemplate = templates.find((item) => item.templateId === selectedTemplateId) || null;
  const selectedTemplateType = selectedTemplate?.templateType || selectedTemplateId;
  const mergedParagraphs = useMemo(() => charUnitsToParagraphs(charUnits), [charUnits]);

  const canCreateDraft = Boolean(selectedTemplateId && selectedTemplate?.available !== false && documentName.trim() && file);
  const canParse = Boolean(draftId && fileId);
  const canParseWithLLM = canParse;
  const canSave = Boolean(draftId && parseId && dirty);
  const canGenerate = Boolean(draftId && parseId && mergedParagraphs.length > 0);

  const setCharUnits = useCallback((updater: (prev: CharUnit[]) => CharUnit[]) => {
    setCharUnitsState(updater);
  }, []);

  function getTypeLabel(type: string) {
    return typeLabelMap[type] || type || '未知';
  }

  const initializeMetadata = useCallback((template: DocumentTemplate) => {
    const next: Record<string, string> = {};
    template.fields.forEach((field) => {
      if (field.defaultValue !== undefined) {
        next[field.fieldKey] = field.defaultValue;
      } else if (DEFAULT_METADATA[field.fieldKey] !== undefined) {
        next[field.fieldKey] = DEFAULT_METADATA[field.fieldKey];
      } else if (field.fieldType === 'select' && field.options?.[0]) {
        next[field.fieldKey] = field.options[0].value;
      } else {
        next[field.fieldKey] = '';
      }
    });
    setMetadata(next);
  }, []);

  const loadTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    setMessage('正在加载模板列表……');

    try {
      const result = await api.getTemplates();
      const nextTemplates = result.templates || [];
      const nextTypes = result.paragraphTypes || DEFAULT_PARAGRAPH_TYPES;
      setTemplates(nextTemplates);
      setParagraphTypes(nextTypes);

      const defaultTemplate =
        nextTemplates.find((template) => template.templateId === DEFAULT_TEMPLATE_ID && template.available !== false) ||
        nextTemplates.find((template) => template.available !== false) ||
        nextTemplates[0];
      if (defaultTemplate) {
        setSelectedTemplateId(defaultTemplate.templateId);
        initializeMetadata(defaultTemplate);
      }

      setMessage(`模板加载成功，共 ${nextTemplates.length} 个模板。`);
    } catch (error) {
      setTemplates(FALLBACK_TEMPLATES);
      setParagraphTypes(DEFAULT_PARAGRAPH_TYPES);
      setSelectedTemplateId(FALLBACK_TEMPLATES[0].templateId);
      initializeMetadata(FALLBACK_TEMPLATES[0]);
      setMessage(`模板接口暂不可用，已使用本地示例模板。原因：${(error as Error).message}`);
    } finally {
      setTemplatesLoading(false);
    }
  }, [api, initializeMetadata]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  function handleTemplateChange(templateId: string) {
    setSelectedTemplateId(templateId);
    const template = templates.find((item) => item.templateId === templateId);
    if (template) initializeMetadata(template);
  }

  function setMetadataField(key: string, value: string) {
    setMetadata((prev) => ({ ...prev, [key]: value }));
  }

  function useSampleParagraphs() {
    setCharUnitsState(paragraphsToCharUnits(SAMPLE_PARAGRAPHS));
    setParseId((prev) => prev || 'parse_demo_001');
    setDirty(false);
    clearBrowserSelection();
    setMessage('已载入示例 paragraphs，并转换为字符级结构。');
  }

  async function createDraft() {
    if (!canCreateDraft || !file) {
      setMessage('请选择模板、填写公文名称，并上传正文文件。');
      return;
    }

    setCreatingDraft(true);
    setOutputFiles([]);
    setMessage('正在创建草稿并上传正文文件……');

    try {
      const result = await api.createDraft({
        templateId: selectedTemplateId,
        templateType: selectedTemplateType,
        documentName,
        metadata,
        file,
      });
      setDraftId(result.draftId || '');
      setFileId(result.bodyFile?.fileId || '');
      setParseId('');
      setCharUnitsState([]);
      setDirty(false);
      setMessage(`草稿创建成功：${result.draftId || ''}。下一步可以选择规则解析或 LLM 解析。`);
    } catch (error) {
      setMessage(`创建草稿失败：${(error as Error).message}`);
    } finally {
      setCreatingDraft(false);
    }
  }

  async function parseByRule() {
    if (!canParse) {
      setMessage('请先创建草稿并确保拿到 draftId 和 fileId。');
      return;
    }

    setParsing(true);
    setMessage('正在基于规则解析正文段落……');

    try {
      const result = await api.parseByRule(draftId, fileId);
      const nextParagraphs = result.paragraphs || [];
      setParseId(result.parseId || '');
      setCharUnitsState(paragraphsToCharUnits(nextParagraphs));
      setDirty(false);
      clearBrowserSelection();
      setMessage(`规则解析成功，获得 ${nextParagraphs.length} 个段落。`);
    } catch (error) {
      setMessage(`规则解析失败：${(error as Error).message}`);
    } finally {
      setParsing(false);
    }
  }

  async function parseByLLM() {
    if (!canParseWithLLM) {
      setMessage('请先创建草稿并确保拿到 draftId 和 fileId。');
      return;
    }

    setParsingWithLLM(true);
    setMessage('正在使用 LLM 解析正文段落……');

    try {
      let streamedParagraphs: ParagraphBlock[] = [];
      const result = await api.parseByLLMStream(draftId, fileId, {
        onStatus: (statusMessage) => {
          if (statusMessage) setMessage(statusMessage);
        },
        onStart: (data) => {
          streamedParagraphs = [];
          setParseId(data.parseId || '');
          setCharUnitsState([]);
          setDirty(false);
          clearBrowserSelection();
          setMessage('LLM 正在返回段落……');
        },
        onParagraph: (paragraph, count) => {
          streamedParagraphs = [...streamedParagraphs, paragraph].sort((left, right) => {
            return (left.index || 0) - (right.index || 0);
          });
          setCharUnitsState(paragraphsToCharUnits(streamedParagraphs));
          setMessage(`LLM 已返回 ${count || streamedParagraphs.length} 个段落，正在继续解析……`);
        },
      });
      const nextParagraphs = result.paragraphs || streamedParagraphs;
      setParseId(result.parseId || '');
      setCharUnitsState(paragraphsToCharUnits(nextParagraphs));
      setDirty(false);
      clearBrowserSelection();
      setMessage(`LLM 解析完成，返回 ${nextParagraphs.length} 个段落。`);
    } catch (error) {
      setMessage(`LLM 解析失败：${(error as Error).message}`);
    } finally {
      setParsingWithLLM(false);
    }
  }

  async function saveParagraphs() {
    if (!canSave) {
      setMessage('当前没有需要保存的修改，或缺少 draftId / parseId。');
      return;
    }

    setSavingParagraphs(true);
    setMessage('正在合并字符级结构，并同步段落类型……');

    try {
      const result = await api.saveParagraphs(draftId, parseId, mergedParagraphs);
      setCharUnitsState(paragraphsToCharUnits(mergedParagraphs));
      setDirty(false);
      clearBrowserSelection();
      setMessage(`段落类型已同步，后端更新 ${result.updatedCount ?? 0} 个段落。`);
    } catch (error) {
      setMessage(`保存失败：${(error as Error).message}`);
    } finally {
      setSavingParagraphs(false);
    }
  }

  async function generateDocument() {
    if (!canGenerate) {
      setMessage('请先完成解析，确保有 draftId、parseId 和最终 paragraphs。');
      return;
    }

    setGenerating(true);
    setOutputFiles([]);
    setMessage('正在生成标准格式公文……');

    try {
      const result = await api.generateDocument(
        {
          templateId: selectedTemplateId,
          templateType: selectedTemplateType,
          documentName,
          parseId,
          metadata,
          paragraphs: mergedParagraphs,
          outputFormat: 'DOCX',
        },
        draftId,
      );
      const files = result.outputFiles || [];
      setOutputFiles(files);
      setMessage(files.length > 0 ? '公文生成成功，可以下载文件。' : '公文生成成功，但后端未返回 outputFiles。');
    } catch (error) {
      setMessage(`公文生成失败：${(error as Error).message}`);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>标准格式公文生成前端</h1>
          <p>模板选择 → 上传正文 → 规则/LLM 解析 → 字符级标注 → 同步类型 → 生成下载。</p>
        </div>
        <div className="step-row">
          <StepBadge done={templates.length > 0} active={templatesLoading}>1 模板</StepBadge>
          <StepBadge done={Boolean(draftId)} active={creatingDraft}>2 草稿</StepBadge>
          <StepBadge done={Boolean(parseId)} active={parsing || parsingWithLLM}>3 解析</StepBadge>
          <StepBadge done={mergedParagraphs.length > 0} active={savingParagraphs}>4 编辑</StepBadge>
          <StepBadge done={outputFiles.length > 0} active={generating}>5 生成</StepBadge>
        </div>
      </header>

      <div className={`layout-grid${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
        <WorkflowSidebar
          collapsed={sidebarCollapsed}
          onCollapsedChange={setSidebarCollapsed}
          apiBase={apiBase}
          setApiBase={setApiBase}
          templates={templates}
          selectedTemplateId={selectedTemplateId}
          selectedTemplate={selectedTemplate}
          onReloadTemplates={loadTemplates}
          templatesLoading={templatesLoading}
          onTemplateChange={handleTemplateChange}
          documentName={documentName}
          setDocumentName={setDocumentName}
          metadata={metadata}
          setMetadataField={setMetadataField}
          file={file}
          setFile={setFile}
          draftId={draftId}
          fileId={fileId}
          parseId={parseId}
          canCreateDraft={canCreateDraft}
          canParse={canParse}
          canParseWithLLM={canParseWithLLM}
          canSave={canSave}
          canGenerate={canGenerate}
          creatingDraft={creatingDraft}
          parsing={parsing}
          parsingWithLLM={parsingWithLLM}
          savingParagraphs={savingParagraphs}
          generating={generating}
          onCreateDraft={createDraft}
          onParseByRule={parseByRule}
          onParseByLLM={parseByLLM}
          onSaveParagraphs={saveParagraphs}
          onGenerate={generateDocument}
          onUseSample={useSampleParagraphs}
          outputFiles={outputFiles}
          getDownloadUrl={(file) => api.downloadUrl(file)}
        />

        <CharacterEditor
          charUnits={charUnits}
          setCharUnits={setCharUnits}
          paragraphTypes={paragraphTypes}
          getTypeLabel={getTypeLabel}
          dirty={dirty}
          setDirty={setDirty}
          message={message}
          setMessage={setMessage}
          isParsing={parsing || parsingWithLLM}
          parseModeLabel={parsingWithLLM ? 'LLM 正在解析正文' : parsing ? '规则正在解析正文' : ''}
        />
      </div>
    </div>
  );
}
