import type { CharUnit, ParagraphBlock, ParagraphSegment, ParagraphSegmentType, ParagraphType } from '../types/document';

const INLINE_LEVEL_3_TYPE = 'LEVEL_3_TITLE_INLINE';
const BODY_TEXT_TYPE = 'BODY_TEXT';
const MIXED_PARAGRAPH_TYPE = 'MIXED_LEVEL_3_BODY';

function createUnitId(): string {
  return `unit_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function paragraphsToCharUnits(paragraphs: ParagraphBlock[]): CharUnit[] {
  const units: CharUnit[] = [];

  paragraphs.forEach((block, blockOffset) => {
    const text = String(block.text || '').replace(/\r\n/g, '\n').replace(/\n+$/g, '');
    const logicalLines = text.split('\n');

    logicalLines.forEach((line, lineOffset) => {
      const segmentText = block.segments?.map((segment) => segment.text || '').join('');
      if (lineOffset === 0 && logicalLines.length === 1 && block.segments?.length && segmentText === line) {
        let charOffset = 0;

        block.segments.forEach((segment, segmentOffset) => {
          Array.from(segment.text || '').forEach((char) => {
            units.push(createTextUnit(block, char, charOffset, segment.type, segmentOffset));
            charOffset += 1;
          });
        });
      } else {
        Array.from(line).forEach((char, charOffset) => {
          units.push(createTextUnit(block, char, charOffset));
        });
      }

      if (lineOffset < logicalLines.length - 1) {
        units.push(createParagraphBreakUnit(block.index, block.type || 'BODY_PARAGRAPH'));
      }
    });

    if (blockOffset < paragraphs.length - 1) {
      units.push(createParagraphBreakUnit(block.index, block.type || 'BODY_PARAGRAPH'));
    }
  });

  return units;
}

function createTextUnit(
  block: ParagraphBlock,
  char: string,
  charOffset: number,
  segmentType?: ParagraphSegmentType,
  segmentOffset?: number,
): CharUnit {
  return {
    id: `p_${block.index}_${segmentOffset ?? 0}_${charOffset}_${createUnitId()}`,
    char,
    type: block.type || 'BODY_PARAGRAPH',
    segmentType,
    sourceType: block.type || 'BODY_PARAGRAPH',
    sourceBlockIndex: block.index,
    sourceCharOffset: charOffset,
    sourceSegments: block.segments,
  };
}

function createParagraphBreakUnit(sourceBlockIndex: number, type: ParagraphType): CharUnit {
  return {
    id: `br_${sourceBlockIndex}_${createUnitId()}`,
    char: '\n',
    type,
    sourceType: type,
    sourceBlockIndex,
    sourceCharOffset: -1,
    isParagraphBreak: true,
  };
}

export function charUnitsToParagraphs(charUnits: CharUnit[]): ParagraphBlock[] {
  const blocks: ParagraphBlock[] = [];
  let current: {
    text: string;
    type: ParagraphType;
    sourceBlockIndex: number;
    sourceSegments?: CharUnit['sourceSegments'];
    preserveSegments: boolean;
    segments: ParagraphSegment[];
  } | null = null;

  function flushCurrent() {
    if (!current || current.text.length === 0) {
      current = null;
      return;
    }

    const block: ParagraphBlock = {
      index: blocks.length + 1,
      text: current.text,
      type: current.type,
    };

    const hasInlineTitle = current.segments.some((segment) => segment.type === INLINE_LEVEL_3_TYPE);
    if (current.type === MIXED_PARAGRAPH_TYPE && hasInlineTitle) {
      block.segments = current.segments;
    } else if (current.preserveSegments && current.sourceSegments) {
      block.segments = current.sourceSegments;
    }

    blocks.push(block);
    current = null;
  }

  charUnits.forEach((unit) => {
    if (unit.isParagraphBreak || unit.char === '\n') {
      flushCurrent();
      return;
    }

    const type = unit.type || 'BODY_PARAGRAPH';

    if (!current || current.type !== type) {
      flushCurrent();
      current = {
        text: '',
        type,
        sourceBlockIndex: unit.sourceBlockIndex,
        sourceSegments: unit.sourceSegments,
        preserveSegments: Boolean(unit.sourceSegments && type === unit.sourceType),
        segments: [],
      };
    } else if (
      current.sourceBlockIndex !== unit.sourceBlockIndex ||
      current.sourceSegments !== unit.sourceSegments ||
      type !== unit.sourceType
    ) {
      current.preserveSegments = false;
    }

    current.text += unit.char;
    appendSegmentChar(current.segments, unit);
  });

  flushCurrent();
  return blocks;
}

function appendSegmentChar(segments: ParagraphSegment[], unit: CharUnit) {
  if (unit.type !== MIXED_PARAGRAPH_TYPE) return;

  const type = unit.segmentType === INLINE_LEVEL_3_TYPE ? INLINE_LEVEL_3_TYPE : BODY_TEXT_TYPE;
  const previous = segments[segments.length - 1];

  if (previous?.type === type) {
    previous.text += unit.char;
  } else {
    segments.push({ type, text: unit.char });
  }
}

export function updateCharUnitsType(
  charUnits: CharUnit[],
  start: number,
  end: number,
  nextType: ParagraphType,
): CharUnit[] {
  const inlineLevel3Update = createInlineLevel3Update(charUnits, start, end, nextType);
  if (inlineLevel3Update) return inlineLevel3Update;

  return charUnits.map((unit, index) => {
    if (index < start || index >= end) return unit;
    if (unit.isParagraphBreak) return unit;
    return {
      ...unit,
      type: nextType,
      segmentType: undefined,
      sourceSegments: undefined,
      sourceType: nextType,
    };
  });
}

function createInlineLevel3Update(
  charUnits: CharUnit[],
  start: number,
  end: number,
  nextType: ParagraphType,
): CharUnit[] | null {
  if (nextType !== 'LEVEL_3_TITLE' && nextType !== MIXED_PARAGRAPH_TYPE) return null;

  const selectedEditableIndexes = getEditableIndexes(charUnits, start, end);
  if (selectedEditableIndexes.length === 0) return null;
  if (charUnits.slice(start, end).some((unit) => unit.isParagraphBreak || unit.char === '\n')) return null;

  const bounds = getParagraphBounds(charUnits, selectedEditableIndexes[0]);
  const paragraphEditableIndexes = getEditableIndexes(charUnits, bounds.start, bounds.end);
  if (selectedEditableIndexes.length >= paragraphEditableIndexes.length) return null;

  const selected = new Set(selectedEditableIndexes);

  return charUnits.map((unit, index) => {
    if (index < bounds.start || index >= bounds.end || unit.isParagraphBreak || unit.char === '\n') {
      return unit;
    }

    return {
      ...unit,
      type: MIXED_PARAGRAPH_TYPE,
      segmentType: selected.has(index) ? INLINE_LEVEL_3_TYPE : BODY_TEXT_TYPE,
      sourceType: MIXED_PARAGRAPH_TYPE,
      sourceSegments: undefined,
    };
  });
}

function getEditableIndexes(charUnits: CharUnit[], start: number, end: number): number[] {
  const indexes: number[] = [];

  for (let index = start; index < end; index += 1) {
    const unit = charUnits[index];
    if (unit && !unit.isParagraphBreak && unit.char !== '\n') {
      indexes.push(index);
    }
  }

  return indexes;
}

function getParagraphBounds(charUnits: CharUnit[], unitIndex: number): { start: number; end: number } {
  let start = unitIndex;
  let end = unitIndex + 1;

  while (start > 0 && !charUnits[start - 1]?.isParagraphBreak && charUnits[start - 1]?.char !== '\n') {
    start -= 1;
  }

  while (end < charUnits.length && !charUnits[end]?.isParagraphBreak && charUnits[end]?.char !== '\n') {
    end += 1;
  }

  return { start, end };
}

export function getTextFromRange(charUnits: CharUnit[], range: { start: number; end: number } | null): string {
  if (!range) return '';
  return charUnits
    .slice(range.start, range.end)
    .map((unit) => unit.char)
    .join('');
}

export function buildRangePreview(text: string, maxLength = 28): string {
  const compact = String(text || '').replace(/\n/g, '\\n');
  return compact.length > maxLength ? `${compact.slice(0, maxLength)}…` : compact;
}

export function createTypeLabelMap<T extends { value: string; label: string }>(types: T[]): Record<string, string> {
  return Object.fromEntries(types.map((item) => [item.value, item.label]));
}

export function normalizeRange(start: number, end: number): { start: number; end: number } {
  return start <= end ? { start, end } : { start: end, end: start };
}
