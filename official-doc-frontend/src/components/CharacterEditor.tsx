import { useMemo, useRef, useState } from 'react';
import type { CharUnit, ParagraphTypeOption } from '../types/document';
import {
  buildRangePreview,
  getTextFromRange,
  normalizeRange,
  updateCharUnitsType,
} from '../utils/paragraphBlocks';
import { clearBrowserSelection, getSelectedUnitRange, getUnitIndexFromPoint, type UnitRange } from '../utils/selection';
import { typeBadgeClass, typeDotClass } from '../utils/typeStyles';

interface CharacterEditorProps {
  charUnits: CharUnit[];
  setCharUnits: (updater: (prev: CharUnit[]) => CharUnit[]) => void;
  paragraphTypes: ParagraphTypeOption[];
  getTypeLabel: (type: string) => string;
  dirty: boolean;
  message: string;
  setMessage: (message: string) => void;
  isParsing: boolean;
  parseModeLabel: string;
}

interface ContextMenuState {
  x: number;
  y: number;
  range: UnitRange;
  text: string;
}

export function CharacterEditor({
  charUnits,
  setCharUnits,
  paragraphTypes,
  getTypeLabel,
  dirty,
  message,
  setMessage,
  isParsing,
  parseModeLabel,
}: CharacterEditorProps) {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const [selectedRange, setSelectedRange] = useState<UnitRange | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  const selectedText = useMemo(() => getTextFromRange(charUnits, selectedRange), [charUnits, selectedRange]);
  const visibleCharCount = useMemo(() => charUnits.filter((unit) => !unit.isParagraphBreak).length, [charUnits]);
  const selectableParagraphTypes = useMemo(
    () => paragraphTypes.filter((type) => type.value !== 'MIXED_LEVEL_3_BODY'),
    [paragraphTypes],
  );

  function closeContextMenu() {
    setContextMenu(null);
  }

  function handleMouseUp() {
    const range = getSelectedUnitRange(editorRef.current);
    if (!range) return;

    const text = getTextFromRange(charUnits, range);
    setSelectedRange(range);
    setMessage(`已选中字符范围 ${range.start} 至 ${range.end}：「${buildRangePreview(text)}」。右键可设置类别。`);
  }

  function handleContextMenu(event: React.MouseEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();

    const clickedIndex = getUnitIndexFromPoint(editorRef.current, event.clientX, event.clientY);
    let range = getSelectedUnitRange(editorRef.current) || selectedRange;

    if (!range && clickedIndex !== null) {
      range = { start: clickedIndex, end: clickedIndex + 1 };
    }

    if (!range) {
      setMessage('请先在字符级编辑区中拖拽选中一段文字，再右键选择类别。');
      closeContextMenu();
      return;
    }

    const text = getTextFromRange(charUnits, range);
    setSelectedRange(range);
    setContextMenu({ x: event.clientX, y: event.clientY, range, text });
  }

  function updateSelectedRangeType(nextType: string) {
    if (!contextMenu?.range) return;

    const { start, end } = normalizeRange(contextMenu.range.start, contextMenu.range.end);
    const hasEditableText = charUnits.slice(start, end).some((unit) => !unit.isParagraphBreak && unit.char !== '\n');
    if (!hasEditableText) {
      setMessage('段落换行分隔符不能单独设置类别，请选择具体文字。');
      setContextMenu(null);
      clearBrowserSelection();
      return;
    }

    setCharUnits((prev) => updateCharUnitsType(prev, start, end, nextType));
    const inlineHint = nextType === 'LEVEL_3_TITLE' ? '；若选择范围位于正文段内，已按段内三级标题 segment 处理' : '';
    setMessage(`已将字符范围 ${start} 至 ${end} 设置为「${getTypeLabel(nextType)}」${inlineHint}：${buildRangePreview(contextMenu.text)}`);
    setContextMenu(null);
    clearBrowserSelection();
  }

  return (
    <main className="panel editor-panel" onClick={closeContextMenu}>
      <div className="panel-title-row with-border">
        <div>
          <h2>字符级编辑区</h2>
          <p className="hint">后端 paragraphs 先拆成字符。拖拽选中任意范围，右键修改类别。</p>
        </div>
        <div className="badge-row">
          {isParsing && <span className="pill active">解析中</span>}
          <span className="pill muted">{visibleCharCount} 字符</span>
          {dirty && <span className="pill warning">待同步</span>}
        </div>
      </div>

      {isParsing && (
        <div className="parse-status-banner" role="status" aria-live="polite">
          <span className="parse-spinner" aria-hidden="true" />
          <div>
            <b>{parseModeLabel || '正在解析正文'}</b>
            <span>{message}</span>
          </div>
        </div>
      )}

      <div ref={editorRef} onMouseUp={handleMouseUp} onContextMenuCapture={handleContextMenu} className="char-editor">
        {isParsing && charUnits.length === 0 && (
          <div className="char-editor-empty-state">
            <b>{parseModeLabel || '正在解析正文'}</b>
            <span>解析结果返回后会自动显示在这里。</span>
          </div>
        )}
        {charUnits.map((unit, unitIndex) => {
          const selected = selectedRange && unitIndex >= selectedRange.start && unitIndex < selectedRange.end;

          if (unit.isParagraphBreak || unit.char === '\n') {
            return (
              <span key={unit.id}>
                <span data-unit-index={unitIndex} data-type={unit.type} className="newline-probe">
                  {'\n'}
                </span>
                <br />
              </span>
            );
          }

          const displayType = unit.segmentType === 'LEVEL_3_TITLE_INLINE' ? 'LEVEL_3_TITLE' : unit.type;
          const title = unit.segmentType === 'LEVEL_3_TITLE_INLINE' ? '段内三级标题' : getTypeLabel(unit.type);

          return (
            <span
              key={unit.id}
              data-unit-index={unitIndex}
              data-type={displayType}
              title={title}
              className={`char-unit ${typeBadgeClass(displayType)} ${selected ? 'selected-char' : ''}`}
            >
              {unit.char}
            </span>
          );
        })}
      </div>

      <div className="message-box">{message}</div>

      <div className="selected-info">
        <b>当前选择：</b>
        {selectedRange ? (
          <span>
            unit {selectedRange.start} - {selectedRange.end}，文本：{buildRangePreview(selectedText)}
          </span>
        ) : (
          <span>尚未选择文字</span>
        )}
      </div>

      <section className="type-list">
        <h3>可选类别</h3>
        <div className="type-chips">
          {selectableParagraphTypes.map((type) => (
            <span key={type.value} className={`type-chip ${typeBadgeClass(type.value)}`}>
              {type.label}
            </span>
          ))}
        </div>
      </section>

      {contextMenu && (
        <div className="context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>
          <div className="context-head">
            <div>
              unit {contextMenu.range.start} - {contextMenu.range.end}
            </div>
            <div className="truncate">{buildRangePreview(contextMenu.text)}</div>
          </div>
          {selectableParagraphTypes.map((type) => (
            <button key={type.value} type="button" onClick={() => updateSelectedRangeType(type.value)}>
              <span className={typeDotClass(type.value)} />
              <span>{type.label}</span>
            </button>
          ))}
        </div>
      )}
    </main>
  );
}
