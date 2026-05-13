import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
const AUTO_SYNC_DELAY_MS = 700;

const DEFAULT_METADATA: Record<string, string> = {
  issuingOrg: '中铁二十四局集团有限公司',
  docNumber: ' 二十四局财资〔2026〕113号',
  securityLevel: 'NONE',
  mainRecipient: '中铁二十四局',
  printOrg: '中铁二十四局集团有限公司',
  ccRecipients: '中铁二十四局集团有限公司',
  issuer: '支卫清',
  printDate: '2026-05-01',
  meetingTitle: '中铁二十四局集团有限公司总经理办公会纪要',
  meetingNumber: '(2024年第13次)',
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
  const [editRevision, setEditRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState('先加载模板，填写字段并上传正文文件。也可以直接用示例数据测试字符级标注。');

  const [creatingDraft, setCreatingDraft] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [parsingWithLLM, setParsingWithLLM] = useState(false);
  const [refiningWithExamples, setRefiningWithExamples] = useState(false);
  const [savingParagraphs, setSavingParagraphs] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [outputFiles, setOutputFiles] = useState<OutputFile[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [baselineParagraphs, setBaselineParagraphs] = useState<ParagraphBlock[]>([]);

  const typeLabelMap = useMemo(() => createTypeLabelMap(paragraphTypes), [paragraphTypes]);
  const selectedTemplate = templates.find((item) => item.templateId === selectedTemplateId) || null;
  const selectedTemplateType = selectedTemplate?.templateType || selectedTemplateId;
  const mergedParagraphs = useMemo(() => charUnitsToParagraphs(charUnits), [charUnits]);

  const canCreateDraft = Boolean(selectedTemplateId && selectedTemplate?.available !== false && documentName.trim() && file);
  const canParse = Boolean(draftId && fileId);
  const canParseWithLLM = canParse;
  const canRefineWithExamples = Boolean(draftId && fileId && parseId && mergedParagraphs.length > 0);
  const canGenerate = Boolean(draftId && parseId && mergedParagraphs.length > 0);

  const latestSyncInputRef = useRef({ draftId: '', parseId: '', charUnits: [] as CharUnit[] });
  const dirtyRef = useRef(false);
  const editRevisionRef = useRef(0);
  const syncedRevisionRef = useRef(0);
  const autoSyncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncInFlightRef = useRef(false);
  const syncPromiseRef = useRef<Promise<boolean> | null>(null);

  const markDirty = useCallback(() => {
    dirtyRef.current = true;
    setDirty(true);
  }, []);

  const markClean = useCallback(() => {
    dirtyRef.current = false;
    setDirty(false);
  }, []);

  const setCharUnits = useCallback((updater: (prev: CharUnit[]) => CharUnit[]) => {
    editRevisionRef.current += 1;
    setEditRevision(editRevisionRef.current);
    markDirty();
    setCharUnitsState(updater);
  }, [markDirty]);

  useEffect(() => {
    latestSyncInputRef.current = { draftId, parseId, charUnits };
  }, [draftId, parseId, charUnits]);

  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  useEffect(() => {
    return () => {
      if (autoSyncTimerRef.current) clearTimeout(autoSyncTimerRef.current);
    };
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
    setBaselineParagraphs(SAMPLE_PARAGRAPHS);
    markClean();
    clearBrowserSelection();
    setMessage('已载入示例 paragraphs，并转换为字符级结构。');
  }

  const syncParagraphs = useCallback(
    async (mode: 'auto' | 'generate' | 'refine' = 'auto') => {
      const forGenerate = mode === 'generate';
      const forRefine = mode === 'refine';

      while (true) {
        if (syncInFlightRef.current) {
          if (!forGenerate && !forRefine) return true;

          setMessage(forRefine ? '正在等待段落类型同步完成，随后重整解析结果……' : '正在等待段落类型同步完成……');
          const runningSync = syncPromiseRef.current;
          if (!runningSync) return false;
          if (!(await runningSync)) return false;
          continue;
        }

        const revision = editRevisionRef.current;
        const { draftId: latestDraftId, parseId: latestParseId, charUnits: latestCharUnits } = latestSyncInputRef.current;
        const hasUnsyncedEdit = dirtyRef.current && revision > syncedRevisionRef.current;
        if (!hasUnsyncedEdit) return true;

        if (!latestDraftId || !latestParseId) {
          if (forGenerate || forRefine) setMessage('请先完成解析，确保有 draftId 和 parseId。');
          return false;
        }

        syncInFlightRef.current = true;
        setSavingParagraphs(true);
        setMessage(
          forGenerate
            ? '正在同步最新段落类型，随后生成公文……'
            : forRefine
              ? '正在同步最新段落类型，随后作为示例交给大模型……'
              : '正在自动同步段落类型……',
        );

        const syncPromise = (async () => {
          try {
            const paragraphs = charUnitsToParagraphs(latestCharUnits);
            const result = await api.saveParagraphs(latestDraftId, latestParseId, paragraphs);

            if (editRevisionRef.current === revision) {
              syncedRevisionRef.current = revision;
              markClean();
            } else {
              syncedRevisionRef.current = Math.max(syncedRevisionRef.current, revision);
            }

            if (!forGenerate) {
              setMessage(`段落类型已自动同步，后端更新 ${result.updatedCount ?? 0} 个段落。`);
            }

            return true;
          } catch (error) {
            markDirty();
            setMessage(`同步失败：${(error as Error).message}。可继续编辑，或点击“生成公文”重试。`);
            return false;
          } finally {
            syncInFlightRef.current = false;
            syncPromiseRef.current = null;
            setSavingParagraphs(false);
          }
        })();

        syncPromiseRef.current = syncPromise;
        const synced = await syncPromise;
        if (!synced) return false;

        const hasMoreUnsyncedEdit = dirtyRef.current && editRevisionRef.current > syncedRevisionRef.current;
        if (forGenerate || forRefine) {
          if (hasMoreUnsyncedEdit) continue;
          return true;
        }

        if (hasMoreUnsyncedEdit) {
          if (autoSyncTimerRef.current) clearTimeout(autoSyncTimerRef.current);
          autoSyncTimerRef.current = setTimeout(() => {
            void syncParagraphs();
          }, AUTO_SYNC_DELAY_MS);
        }

        return true;
      }
    },
    [api, markClean, markDirty],
  );

  useEffect(() => {
    if (!dirty || !draftId || !parseId || editRevision <= syncedRevisionRef.current) return;

    if (autoSyncTimerRef.current) clearTimeout(autoSyncTimerRef.current);
    autoSyncTimerRef.current = setTimeout(() => {
      void syncParagraphs();
    }, AUTO_SYNC_DELAY_MS);
  }, [dirty, draftId, parseId, editRevision, syncParagraphs]);

  async function createDraft() {
    if (!canCreateDraft || !file) {
      setMessage('请选择模板、填写公文名称，并上传正文文件。');
      return;
    }

    setCreatingDraft(true);
    setOutputFiles([]);
    setMessage('正在上传正文文件……');

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
      setBaselineParagraphs([]);
      markClean();
      setMessage('文件上传成功。下一步可以选择规则解析或大模型解析。');
    } catch (error) {
      setMessage(`上传文件失败：${(error as Error).message}`);
    } finally {
      setCreatingDraft(false);
    }
  }

  async function parseByRule() {
    if (!canParse) {
      setMessage('请先上传文件，并确保接口已返回 draftId 和 fileId。');
      return;
    }

    setParsing(true);
    setMessage('正在基于规则解析正文段落……');

    try {
      const result = await api.parseByRule(draftId, fileId);
      const nextParagraphs = result.paragraphs || [];
      setParseId(result.parseId || '');
      setCharUnitsState(paragraphsToCharUnits(nextParagraphs));
      setBaselineParagraphs(nextParagraphs);
      markClean();
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
      setMessage('请先上传文件，并确保接口已返回 draftId 和 fileId。');
      return;
    }

    setParsingWithLLM(true);
    setMessage('正在使用大模型解析正文段落……');

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
          markClean();
          clearBrowserSelection();
          setMessage('大模型正在返回段落……');
        },
        onParagraph: (paragraph, count) => {
          streamedParagraphs = [...streamedParagraphs, paragraph].sort((left, right) => {
            return (left.index || 0) - (right.index || 0);
          });
          setCharUnitsState(paragraphsToCharUnits(streamedParagraphs));
          setMessage(`大模型已返回 ${count || streamedParagraphs.length} 个段落，正在继续解析……`);
        },
      });
      const nextParagraphs = result.paragraphs || streamedParagraphs;
      setParseId(result.parseId || '');
      setCharUnitsState(paragraphsToCharUnits(nextParagraphs));
      setBaselineParagraphs(nextParagraphs);
      markClean();
      clearBrowserSelection();
      setMessage(`大模型解析完成，返回 ${nextParagraphs.length} 个段落。`);
    } catch (error) {
      setMessage(`大模型解析失败：${(error as Error).message}`);
    } finally {
      setParsingWithLLM(false);
    }
  }

  async function refineByExamples() {
    if (!canRefineWithExamples) {
      setMessage('请先完成一次解析，并在编辑区修正部分段落类型。');
      return;
    }

    if (autoSyncTimerRef.current) {
      clearTimeout(autoSyncTimerRef.current);
      autoSyncTimerRef.current = null;
    }

    setRefiningWithExamples(true);

    try {
      const synced = await syncParagraphs('refine');
      if (!synced) return;

      const latest = latestSyncInputRef.current;
      const latestParagraphs = charUnitsToParagraphs(latest.charUnits);
      const correctionExamples = getCorrectionExamples(latestParagraphs, baselineParagraphs);
      const examples = correctionExamples.length > 0 ? correctionExamples : latestParagraphs.slice(0, 40);
      const exampleHint =
        correctionExamples.length > 0
          ? `已提取 ${correctionExamples.length} 条用户修正示例`
          : '未检测到明显改动，将使用当前解析结果作为参考示例';

      setMessage(`${exampleHint}，正在请求大模型重新整理解析结果……`);
      let streamedParagraphs: ParagraphBlock[] = [];
      const result = await api.reclassifyByExamplesStream(
        latest.draftId,
        latest.parseId,
        fileId,
        latestParagraphs,
        examples,
        {
          onStatus: (statusMessage) => {
            if (statusMessage) setMessage(statusMessage);
          },
          onStart: (data) => {
            streamedParagraphs = [];
            setParseId(data.parseId || latest.parseId);
            setCharUnitsState([]);
            markClean();
            clearBrowserSelection();
            setMessage('大模型正在按修改示例返回段落……');
          },
          onParagraph: (paragraph, count) => {
            streamedParagraphs = [...streamedParagraphs, paragraph].sort((left, right) => {
              return (left.index || 0) - (right.index || 0);
            });
            setCharUnitsState(paragraphsToCharUnits(streamedParagraphs));
            setMessage(`示例重整已返回 ${count || streamedParagraphs.length} 个段落，正在继续解析……`);
          },
        },
      );
      const nextParagraphs = result.paragraphs || streamedParagraphs;
      setParseId(result.parseId || latest.parseId);
      setCharUnitsState(paragraphsToCharUnits(nextParagraphs));
      setBaselineParagraphs(nextParagraphs);
      markClean();
      clearBrowserSelection();
      setMessage(`已基于用户示例重整解析结果，返回 ${nextParagraphs.length} 个段落。`);
    } catch (error) {
      setMessage(`示例重整失败：${(error as Error).message}`);
    } finally {
      setRefiningWithExamples(false);
    }
  }

  async function generateDocument() {
    if (!canGenerate) {
      setMessage('请先完成解析，确保有 draftId、parseId 和最终 paragraphs。');
      return;
    }

    if (autoSyncTimerRef.current) {
      clearTimeout(autoSyncTimerRef.current);
      autoSyncTimerRef.current = null;
    }

    setGenerating(true);
    setOutputFiles([]);

    try {
      const synced = await syncParagraphs('generate');
      if (!synced) return;

      const latest = latestSyncInputRef.current;
      const latestParagraphs = charUnitsToParagraphs(latest.charUnits);
      setMessage('正在生成标准格式公文……');
      const result = await api.generateDocument(
        {
          templateId: selectedTemplateId,
          templateType: selectedTemplateType,
          documentName,
          parseId: latest.parseId,
          metadata,
          paragraphs: latestParagraphs,
          outputFormat: 'DOCX',
        },
        latest.draftId,
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
          <p>模板选择 → 上传正文 → 规则/大模型解析 → 字符级标注 → 生成下载。</p>
        </div>
        <div className="step-row">
          <StepBadge done={templates.length > 0} active={templatesLoading}>1 模板</StepBadge>
          <StepBadge done={Boolean(draftId)} active={creatingDraft}>2 上传</StepBadge>
          <StepBadge done={Boolean(parseId)} active={parsing || parsingWithLLM || refiningWithExamples}>3 解析</StepBadge>
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
          canRefineWithExamples={canRefineWithExamples}
          canGenerate={canGenerate}
          creatingDraft={creatingDraft}
          parsing={parsing}
          parsingWithLLM={parsingWithLLM}
          refiningWithExamples={refiningWithExamples}
          savingParagraphs={savingParagraphs}
          generating={generating}
          onCreateDraft={createDraft}
          onParseByRule={parseByRule}
          onParseByLLM={parseByLLM}
          onRefineByExamples={refineByExamples}
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
          message={message}
          setMessage={setMessage}
          isParsing={parsing || parsingWithLLM || refiningWithExamples}
          parseModeLabel={
            refiningWithExamples ? '大模型正在按示例重整解析' : parsingWithLLM ? '大模型正在解析正文' : parsing ? '规则正在解析正文' : ''
          }
        />
      </div>
    </div>
  );
}

function getCorrectionExamples(current: ParagraphBlock[], baseline: ParagraphBlock[]): ParagraphBlock[] {
  if (baseline.length === 0) return [];

  const baselineByIndex = new Map(baseline.map((paragraph) => [paragraph.index, paragraph]));
  const baselineByText = new Map<string, ParagraphBlock[]>();
  baseline.forEach((paragraph) => {
    const key = normalizeParagraphText(paragraph.text);
    const list = baselineByText.get(key) || [];
    list.push(paragraph);
    baselineByText.set(key, list);
  });

  return current.filter((paragraph) => {
    const sameIndex = baselineByIndex.get(paragraph.index);
    if (sameIndex && normalizeParagraphText(sameIndex.text) === normalizeParagraphText(paragraph.text)) {
      return paragraphChanged(paragraph, sameIndex);
    }

    const candidates = baselineByText.get(normalizeParagraphText(paragraph.text)) || [];
    if (candidates.length === 0) return true;
    return candidates.every((candidate) => paragraphChanged(paragraph, candidate));
  });
}

function paragraphChanged(current: ParagraphBlock, baseline: ParagraphBlock): boolean {
  return (
    current.type !== baseline.type ||
    normalizeSegments(current.segments) !== normalizeSegments(baseline.segments) ||
    normalizeParagraphText(current.text) !== normalizeParagraphText(baseline.text)
  );
}

function normalizeSegments(segments?: ParagraphBlock['segments']): string {
  return JSON.stringify(
    (segments || []).map((segment) => ({
      type: segment.type,
      text: normalizeParagraphText(segment.text),
    })),
  );
}

function normalizeParagraphText(text: string): string {
  return String(text || '').replace(/\s+/g, ' ').trim();
}
