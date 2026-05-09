import { ApiClient } from './client';
import type {
  CreateDraftResult,
  DocumentTemplate,
  GenerateResult,
  OutputFile,
  ParagraphBlock,
  ParagraphTypeOption,
  ParseResult,
  SaveParagraphsResult,
  TemplateTypeOption,
} from '../types/document';

export interface TemplatesResponse {
  templateTypes?: TemplateTypeOption[];
  templates: DocumentTemplate[];
  paragraphTypes: ParagraphTypeOption[];
}

export interface CreateDraftInput {
  templateId?: string;
  templateType?: string;
  documentName: string;
  metadata: Record<string, string>;
  file: File;
}

export interface GenerateInput {
  templateId?: string;
  templateType: string;
  documentName?: string;
  parseId: string;
  metadata: Record<string, string>;
  paragraphs: ParagraphBlock[];
  outputFormat?: 'DOCX' | string;
}

export type ParseStrategy = 'RULE' | 'LLM';

export interface ParseStreamHandlers {
  onStatus?: (message: string) => void;
  onStart?: (data: Pick<ParseResult, 'draftId' | 'parseId' | 'strategy'>) => void;
  onParagraph?: (paragraph: ParagraphBlock, count: number) => void;
}

export class DocumentApi {
  private client: ApiClient;

  constructor(client: ApiClient) {
    this.client = client;
  }

  async getTemplates(): Promise<TemplatesResponse> {
    return this.client.json<TemplatesResponse>('/document-templates');
  }

  async createDraft(input: CreateDraftInput): Promise<CreateDraftResult> {
    const formData = new FormData();
    if (input.templateType) formData.append('templateType', input.templateType);
    if (input.templateId) formData.append('templateId', input.templateId);
    formData.append('documentName', input.documentName);
    formData.append('metadata', JSON.stringify(input.metadata));
    formData.append('file', input.file);

    return this.client.json<CreateDraftResult>('/document-drafts', {
      method: 'POST',
      body: formData,
    });
  }

  async parseBody(draftId: string, fileId: string, strategy: ParseStrategy): Promise<ParseResult> {
    return this.client.json<ParseResult>(`/document-drafts/${encodeURIComponent(draftId)}/body/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fileId,
        strategy,
        options: {
          splitByEmptyLine: true,
          detectTitle: true,
          detectHeadingNumber: true,
          detectSignatureAndDate: true,
        },
      }),
    });
  }

  async parseByRule(draftId: string, fileId: string): Promise<ParseResult> {
    return this.parseBody(draftId, fileId, 'RULE');
  }

  async parseByLLM(draftId: string, fileId: string): Promise<ParseResult> {
    return this.parseBody(draftId, fileId, 'LLM');
  }

  async parseByLLMStream(draftId: string, fileId: string, handlers: ParseStreamHandlers = {}): Promise<ParseResult> {
    return this.parseBodyStream(draftId, fileId, 'LLM', handlers);
  }

  async parseBodyStream(
    draftId: string,
    fileId: string,
    strategy: ParseStrategy,
    handlers: ParseStreamHandlers = {},
  ): Promise<ParseResult> {
    const response = await fetch(this.client.endpoint(`/document-drafts/${encodeURIComponent(draftId)}/body/parse/stream`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fileId, strategy }),
    });

    if (!response.ok) {
      const text = await response.text();
      const message = parseErrorMessage(text) || `HTTP ${response.status}`;
      throw new Error(message);
    }

    if (!response.body) {
      throw new Error('浏览器不支持流式响应');
    }

    return readSseParseStream(response.body, handlers);
  }

  async classifyByLLM(draftId: string, parseId: string, paragraphs: ParagraphBlock[]): Promise<ParseResult> {
    return this.client.json<ParseResult>(`/document-drafts/${encodeURIComponent(draftId)}/body/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        parseId,
        strategy: 'LLM',
        paragraphs,
      }),
    });
  }

  async saveParagraphs(
    draftId: string,
    parseId: string,
    paragraphs: ParagraphBlock[],
  ): Promise<SaveParagraphsResult> {
    const updates = paragraphs.map((paragraph) => ({
      index: paragraph.index,
      type: paragraph.type,
    }));

    return this.client.json<SaveParagraphsResult>(`/document-drafts/${encodeURIComponent(draftId)}/body/paragraph-types`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parseId, updates }),
    });
  }

  async generateDocument(input: GenerateInput, draftId: string): Promise<GenerateResult> {
    return this.client.json<GenerateResult>(`/document-drafts/${encodeURIComponent(draftId)}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        templateType: input.templateType,
        templateId: input.templateId,
        documentName: input.documentName,
        parseId: input.parseId,
        outputFormat: input.outputFormat || 'DOCX',
        metadata: input.metadata,
        paragraphs: input.paragraphs,
        options: {
          includePageNumber: true,
          strictOfficialFormat: true,
        },
      }),
    });
  }

  downloadUrl(file: OutputFile): string {
    return this.client.resolveUrl(file.downloadUrl || `/api/v1/files/${encodeURIComponent(file.fileId)}/download`);
  }
}

async function readSseParseStream(body: ReadableStream<Uint8Array>, handlers: ParseStreamHandlers): Promise<ParseResult> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let eventName = 'message';
  let dataLines: string[] = [];
  let finalResult: ParseResult | null = null;

  function dispatchEvent() {
    if (dataLines.length === 0) {
      eventName = 'message';
      return;
    }

    const rawData = dataLines.join('\n');
    const currentEvent = eventName || 'message';
    eventName = 'message';
    dataLines = [];

    let payload: any;
    try {
      payload = JSON.parse(rawData);
    } catch {
      return;
    }

    if (currentEvent === 'status') {
      handlers.onStatus?.(String(payload.message || ''));
    } else if (currentEvent === 'parseStart') {
      handlers.onStart?.(payload);
    } else if (currentEvent === 'paragraph') {
      handlers.onParagraph?.(payload.paragraph, Number(payload.count || 0));
    } else if (currentEvent === 'done') {
      finalResult = payload as ParseResult;
    } else if (currentEvent === 'error') {
      throw new Error(payload.message || '流式解析失败');
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line === '') {
        dispatchEvent();
      } else if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    if (done) break;
  }

  if (buffer || dataLines.length > 0) {
    dispatchEvent();
  }

  if (!finalResult) {
    throw new Error('流式解析未返回完成事件');
  }

  return finalResult;
}

function parseErrorMessage(text: string): string {
  try {
    const payload = JSON.parse(text);
    return payload?.message || '';
  } catch {
    return '';
  }
}
