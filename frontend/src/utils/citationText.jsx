import React from 'react';

/**
 * Citations arrive with markdown-style *italics* around the parts the Bluebook
 * italicizes. Render those as real emphasis rather than showing the asterisks.
 */
export function renderCitation(text) {
  if (!text) return null;
  return text.split(/(\*[^*]+\*)/g).map((part, i) =>
    part.startsWith('*') && part.endsWith('*') && part.length > 2
      ? <em key={i}>{part.slice(1, -1)}</em>
      : part
  );
}

/** Strip the markers, for a plain-text fallback. */
export function toPlainText(text) {
  return (text || '').replace(/\*([^*]+)\*/g, '$1');
}

/** Convert the markers to HTML emphasis, for a rich-text fallback. */
export function toHtml(text) {
  const escaped = (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return escaped.replace(/\*([^*]+)\*/g, '<i>$1</i>');
}

/**
 * Copy a citation so it pastes correctly into a word processor.
 *
 * Writing both text/html and text/plain lets Word, Google Docs and Pages take
 * the HTML flavor and render real italics, while a plain-text target still
 * gets readable output instead of asterisks.
 *
 * Returns true on success. Callers should surface failure rather than
 * silently appearing to have copied.
 */
export async function copyCitation(text) {
  if (!text) return false;

  const plain = toPlainText(text);
  const html = toHtml(text);

  try {
    if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([plain], { type: 'text/plain' }),
        }),
      ]);
      return true;
    }
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(plain);
      return true;
    }
  } catch {
    // Fall through to the legacy path below.
  }

  try {
    const area = document.createElement('textarea');
    area.value = plain;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
