import type { DocumentTemplate, ParagraphBlock, ParagraphTypeOption } from '../types/document';

export const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const DEFAULT_PARAGRAPH_TYPES: ParagraphTypeOption[] = [
  { value: 'MAIN_TITLE', label: '主标题' },
  { value: 'SUB_TITLE', label: '副标题' },
  { value: 'RECIPIENT', label: '主送机关' },
  { value: 'BODY_PARAGRAPH', label: '普通正文' },
  { value: 'LEVEL_1_TITLE', label: '一级标题' },
  { value: 'LEVEL_2_TITLE', label: '二级标题' },
  { value: 'LEVEL_3_TITLE', label: '三级标题' },
  { value: 'MIXED_LEVEL_3_BODY', label: '三级标题+同段正文' },
  { value: 'ATTACHMENT_HEADER', label: '附件标题' },
  { value: 'ATTACHMENT_ITEM', label: '附件条目' },
  { value: 'APPENDIX_TITLE', label: '附件正文标题' },
  { value: 'CHAPTER_TITLE', label: '章标题' },
  { value: 'ARTICLE_PARAGRAPH', label: '条文正文' },
  { value: 'SIGNING_COMPANY', label: '落款单位' },
  { value: 'SIGNING_DATE', label: '落款日期' },
  { value: 'CONTACT_INFO', label: '联系人信息' },
];

function redheadFields(input: {
  issuingOrg: string;
  docNumber: string;
  ccRecipients: string;
  issuer?: string | null;
  printOrg: string;
  printDate?: string;
}): DocumentTemplate['fields'] {
  const fields: DocumentTemplate['fields'] = [
    {
      fieldKey: 'issuingOrg',
      fieldName: '发文单位',
      fieldType: 'text',
      required: false,
      defaultValue: input.issuingOrg,
      placeholder: '请输入发文单位',
    },
    {
      fieldKey: 'docNumber',
      fieldName: '发文字号',
      fieldType: 'text',
      required: false,
      defaultValue: input.docNumber,
      placeholder: '例如：中铁二十四局办〔2026〕12号',
    },
    {
      fieldKey: 'ccRecipients',
      fieldName: '抄送机关',
      fieldType: 'textarea',
      required: false,
      defaultValue: input.ccRecipients,
      placeholder: '请输入抄送机关',
    },
  ];

  if (input.issuer !== null && input.issuer !== undefined) {
    fields.push({
      fieldKey: 'issuer',
      fieldName: '签发人',
      fieldType: 'text',
      required: false,
      defaultValue: input.issuer || '',
      placeholder: '请输入签发人',
    });
  }

  fields.push(
    {
      fieldKey: 'printOrg',
      fieldName: '印发机关',
      fieldType: 'text',
      required: false,
      defaultValue: input.printOrg,
      placeholder: '请输入印发机关',
    },
    {
      fieldKey: 'printDate',
      fieldName: '印发日期',
      fieldType: 'date',
      required: false,
      defaultValue: input.printDate || '2026-05-01',
    },
  );

  return fields;
}

function simpleRedheadFields(input: {
  issuingOrg: string;
  docNumber: string;
  printOrg: string;
  printDate?: string;
}): DocumentTemplate['fields'] {
  return [
    {
      fieldKey: 'issuingOrg',
      fieldName: '发文单位',
      fieldType: 'text',
      required: false,
      defaultValue: input.issuingOrg,
      placeholder: '请输入发文单位',
    },
    {
      fieldKey: 'docNumber',
      fieldName: '发文字号',
      fieldType: 'text',
      required: false,
      defaultValue: input.docNumber,
      placeholder: '例如：中铁二十四局函〔2026〕5号',
    },
    {
      fieldKey: 'printOrg',
      fieldName: '印发机关',
      fieldType: 'text',
      required: false,
      defaultValue: input.printOrg,
      placeholder: '请输入印发机关',
    },
    {
      fieldKey: 'printDate',
      fieldName: '印发日期',
      fieldType: 'date',
      required: false,
      defaultValue: input.printDate || '2026-05-01',
    },
  ];
}

function meetingMinutesFields(): DocumentTemplate['fields'] {
  return [
    {
      fieldKey: 'meetingTitle',
      fieldName: '纪要标题',
      fieldType: 'text',
      required: false,
      defaultValue: '中铁二十四局集团有限公司总经理办公会纪要',
      placeholder: '请输入会议纪要标题',
    },
    {
      fieldKey: 'meetingNumber',
      fieldName: '纪要编号',
      fieldType: 'text',
      required: false,
      defaultValue: '(2024年第13次)',
      placeholder: '例如：〔2026〕3号',
    },
    {
      fieldKey: 'printOrg',
      fieldName: '印发机关',
      fieldType: 'text',
      required: false,
      defaultValue: '中铁二十四局集团有限公司办公室',
      placeholder: '请输入印发机关',
    },
    {
      fieldKey: 'printDate',
      fieldName: '印发日期',
      fieldType: 'date',
      required: false,
      defaultValue: '2026-05-01',
    },
    {
      fieldKey: 'ccRecipients',
      fieldName: '抄送机关',
      fieldType: 'textarea',
      required: false,
      defaultValue: '集团公司领导',
      placeholder: '请输入抄送机关',
    },
  ];
}

export const FALLBACK_TEMPLATES: DocumentTemplate[] = [
  {
    templateId: 'LETTER',
    templateName: '上行文',
    templateType: 'LETTER',
    description: '适用于请示、报告等上行文',
    version: '1.0.0',
    status: 'ACTIVE',
    available: true,
    fields: redheadFields({
      issuingOrg: '中铁二十四局集团有限公司',
      docNumber: ' 二十四局财资〔2026〕113号',
      ccRecipients: '中铁二十四局集团有限公司',
      issuer: '支卫清',
      printOrg: '中铁二十四局集团有限公司',
    }),
  },
  {
    templateId: 'DOWNWARD',
    templateName: '下行文',
    templateType: 'DOWNWARD',
    description: '适用于通知、批复等下行文',
    version: '1.0.0',
    status: 'ACTIVE',
    available: true,
    fields: redheadFields({
      issuingOrg: '中铁二十四局集团有限公司',
      docNumber: '二十四局财资〔2026〕113号',
      ccRecipients: '中铁二十四局集团有限公司',
      issuer: null,
      printOrg: '中铁二十四局集团有限公司',
    }),
  },
  {
    templateId: 'PARALLEL',
    templateName: '平行文',
    templateType: 'PARALLEL',
    description: '适用于函、意见等平行文',
    version: '1.0.0',
    status: 'ACTIVE',
    available: true,
    fields: simpleRedheadFields({
      issuingOrg: '中铁二十四局集团有限公司',
      docNumber: ' 二十四局财资〔2026〕113号',
      printOrg: '中铁二十四局集团有限公司',
    }),
  },
  {
    templateId: 'MEETING_MINUTES',
    templateName: '会议纪要',
    templateType: 'MEETING_MINUTES',
    description: '适用于会议纪要类公文',
    version: '1.0.0',
    status: 'ACTIVE',
    available: true,
    fields: meetingMinutesFields(),
  },
  {
    templateId: 'PLAIN_ARTICLE',
    templateName: '无红头交流文件',
    templateType: 'PLAIN_ARTICLE',
    description: '不含红头，仅保留交流材料标题和正文格式',
    version: '1.0.0',
    status: 'ACTIVE',
    available: true,
    fields: [],
  },
];

export const SAMPLE_PARAGRAPHS: ParagraphBlock[] = [
  { index: 1, text: '正文模板格式确认样例', type: 'MAIN_TITLE' },
  { index: 2, text: '用于确认公文正文标题层级、段落缩进和字体样式', type: 'SUB_TITLE' },
  { index: 3, text: '中国铁道建筑集团有限公司：', type: 'RECIPIENT' },
  {
    index: 4,
    text: '本文档用于确认当前“上行文正文模板”的实际排版效果。请重点查看主标题、副标题、普通正文、一级标题、二级标题、三级标题、附件和落款等内容是否符合实际公文要求。',
    type: 'BODY_PARAGRAPH',
  },
  { index: 5, text: '一、一级标题样式', type: 'LEVEL_1_TITLE' },
  {
    index: 6,
    text: '一级标题应单独成段，当前配置为黑体三号，段落首行缩进两个字符。一级标题下方的普通正文为仿宋_GB2312三号，首行缩进两个字符，两端对齐。',
    type: 'BODY_PARAGRAPH',
  },
  { index: 7, text: '（一）二级标题样式', type: 'LEVEL_2_TITLE' },
  {
    index: 8,
    text: '二级标题应与正文换行，单独成段。当前配置为楷体三号，段落首行缩进两个字符。二级标题后面的说明正文另起一段。',
    type: 'BODY_PARAGRAPH',
  },
  {
    index: 9,
    text: '1.三级标题样式。三级标题与正文之间不换行，处在同一个 Word 段落中，但三级标题本身加粗，后续正文继续使用正文样式。',
    type: 'MIXED_LEVEL_3_BODY',
    segments: [
      { type: 'LEVEL_3_TITLE_INLINE', text: '1.三级标题样式。' },
      { type: 'BODY_TEXT', text: '三级标题与正文之间不换行，处在同一个 Word 段落中，但三级标题本身加粗，后续正文继续使用正文样式。' },
    ],
  },
  { index: 10, text: '二、只有一级标题和三级标题的情况', type: 'LEVEL_1_TITLE' },
  {
    index: 11,
    text: '1.无二级标题时的三级标题。文中允许一级标题下直接出现三级标题，不强制要求必须存在二级标题。此处用于确认这种结构下的排版效果。',
    type: 'MIXED_LEVEL_3_BODY',
  },
  { index: 12, text: '附件：', type: 'ATTACHMENT_HEADER' },
  { index: 13, text: '1．正文模板格式确认清单', type: 'ATTACHMENT_ITEM' },
  { index: 14, text: '2．正文结构化 blocks 示例', type: 'ATTACHMENT_ITEM' },
  { index: 15, text: '以上样式如无问题，可作为后续正文生成的基础格式配置。', type: 'BODY_PARAGRAPH' },
  { index: 16, text: '中铁二十四局集团有限公司', type: 'SIGNING_COMPANY' },
  { index: 17, text: '2026年4月30日', type: 'SIGNING_DATE' },
  { index: 18, text: '（联系人：模板确认人，联系电话：00000000000）', type: 'CONTACT_INFO' },
];
