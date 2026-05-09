export type TemplateType =
  | 'REPORT'
  | 'NOTICE'
  | 'REQUEST'
  | 'LETTER'
  | 'MEETING_MINUTES'
  | 'PLAIN_ARTICLE'
  | 'OTHER';

export type ParagraphType =
  | 'MAIN_TITLE'
  | 'SUB_TITLE'
  | 'RECIPIENT'
  | 'BODY_PARAGRAPH'
  | 'LEVEL_1_TITLE'
  | 'LEVEL_2_TITLE'
  | 'LEVEL_3_TITLE'
  | 'MIXED_LEVEL_3_BODY'
  | 'ATTACHMENT_HEADER'
  | 'ATTACHMENT_ITEM'
  | 'SIGNING_COMPANY'
  | 'SIGNING_DATE'
  | 'CONTACT_INFO'
  | string;

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
  requestId?: string;
}

export interface TemplateFieldOption {
  label: string;
  value: string;
}

export interface TemplateTypeOption {
  label: string;
  value: TemplateType | string;
}

export interface TemplateField {
  fieldKey: string;
  fieldName: string;
  fieldType: 'text' | 'textarea' | 'select' | 'date' | string;
  required?: boolean;
  defaultValue?: string;
  placeholder?: string;
  maxLength?: number;
  options?: TemplateFieldOption[];
}

export interface DocumentTemplate {
  templateId: string;
  templateName: string;
  templateType: TemplateType | string;
  description?: string;
  version?: string;
  status?: string;
  available?: boolean;
  fields: TemplateField[];
}

export interface ParagraphTypeOption {
  value: ParagraphType;
  label: string;
}

export interface ParagraphSegment {
  type: 'LEVEL_3_TITLE_INLINE' | 'BODY_TEXT' | string;
  text: string;
}

export type ParagraphSegmentType = ParagraphSegment['type'];

export interface ParagraphBlock {
  index: number;
  text: string;
  type: ParagraphType;
  segments?: ParagraphSegment[];
}

export interface CharUnit {
  id: string;
  char: string;
  type: ParagraphType;
  segmentType?: ParagraphSegmentType;
  sourceType?: ParagraphType;
  sourceBlockIndex: number;
  sourceCharOffset: number;
  isParagraphBreak?: boolean;
  sourceSegments?: ParagraphSegment[];
}

export interface BodyFileInfo {
  fileId: string;
  fileName: string;
  fileType?: string;
  fileSize?: number;
  uploadTime?: string;
}

export interface CreateDraftResult {
  draftId: string;
  templateId: string;
  templateType?: TemplateType | string;
  documentName: string;
  metadata: Record<string, string>;
  bodyFile: BodyFileInfo;
  status?: string;
}

export interface ParseResult {
  draftId: string;
  parseId: string;
  strategy: 'RULE' | 'LLM' | string;
  paragraphs: ParagraphBlock[];
}

export interface SaveParagraphsResult {
  draftId?: string;
  parseId?: string;
  updatedCount?: number;
  paragraphs?: ParagraphBlock[];
}

export interface OutputFile {
  fileId: string;
  fileType?: string;
  fileName?: string;
  downloadUrl?: string;
}

export interface GenerateResult {
  draftId: string;
  documentId?: string;
  status: 'GENERATED' | 'FAILED' | string;
  outputFiles: OutputFile[];
}
