import { normalizeRange } from './paragraphBlocks';

export interface UnitRange {
  start: number;
  end: number;
}

export function getClosestUnitIndexFromNode(node: Node | null, editorElement: HTMLElement | null): number | null {
  if (!node || !editorElement) return null;

  const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  if (!(element instanceof HTMLElement)) return null;

  const unitElement = element.closest('[data-unit-index]');
  if (!(unitElement instanceof HTMLElement) || !editorElement.contains(unitElement)) return null;

  const rawIndex = unitElement.dataset.unitIndex;
  if (!rawIndex) return null;

  return Number(rawIndex);
}

export function getUnitIndexFromPoint(editorElement: HTMLElement | null, x: number, y: number): number | null {
  if (!editorElement) return null;

  const elements = document.elementsFromPoint(x, y);
  const unitElement = elements.find(
    (element) => element instanceof HTMLElement && element.hasAttribute('data-unit-index'),
  );

  if (!(unitElement instanceof HTMLElement) || !editorElement.contains(unitElement)) return null;

  return Number(unitElement.dataset.unitIndex);
}

export function getSelectedUnitRange(editorElement: HTMLElement | null): UnitRange | null {
  const selection = window.getSelection();

  if (!selection || selection.rangeCount === 0 || selection.isCollapsed || !editorElement) return null;

  const anchorIndex = getClosestUnitIndexFromNode(selection.anchorNode, editorElement);
  const focusIndex = getClosestUnitIndexFromNode(selection.focusNode, editorElement);

  if (anchorIndex === null || focusIndex === null) return null;

  const { start, end } = normalizeRange(anchorIndex, focusIndex);
  return { start, end: end + 1 };
}

export function clearBrowserSelection(): void {
  const selection = window.getSelection();
  if (selection) selection.removeAllRanges();
}
