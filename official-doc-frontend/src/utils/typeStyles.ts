import type { ParagraphType } from '../types/document';

export function typeBadgeClass(type: ParagraphType): string {
  if (type === 'MAIN_TITLE' || type === 'TITLE') return 'type-title';
  if (type === 'SUB_TITLE' || type === 'SUBTITLE') return 'type-subtitle';
  if (type === 'RECIPIENT' || type === 'MAIN_RECIPIENT') return 'type-main-recipient';
  if (type === 'LEVEL_1_TITLE' || type === 'SUBTITLE_LEVEL_1') return 'type-heading-1';
  if (type === 'LEVEL_2_TITLE' || type === 'SUBTITLE_LEVEL_2') return 'type-heading-2';
  if (type === 'LEVEL_3_TITLE' || type === 'SUBTITLE_LEVEL_3') return 'type-heading-3';
  if (type === 'MIXED_LEVEL_3_BODY' || type === 'BODY_PARAGRAPH' || type === 'NORMAL_TEXT') return 'type-normal';
  if (type === 'ATTACHMENT_HEADER' || type === 'ATTACHMENT_TITLE') return 'type-attachment-title';
  if (type === 'ATTACHMENT_ITEM') return 'type-attachment-item';
  if (type === 'SIGNING_COMPANY' || type === 'SIGNATURE') return 'type-signature';
  if (type === 'SIGNING_DATE' || type === 'DATE') return 'type-date';
  if (type === 'CONTACT_INFO') return 'type-contact';
  return 'type-unknown';
}

export function typeDotClass(type: ParagraphType): string {
  return `${typeBadgeClass(type)} type-dot`;
}
