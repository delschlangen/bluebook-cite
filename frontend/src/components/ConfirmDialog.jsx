import React, { useEffect, useId, useRef } from 'react';

/**
 * A question in the page that has to be answered before anything else: "are you sure?". Not
 * window.confirm, which phones show as a browser box with the page's address on it, cannot be
 * styled, and is blocked in some embedded views.
 *
 * Focus starts on the safe answer (`cancelLabel`), Tab stays inside, Escape and a tap outside are
 * that same answer. The caller puts focus back where it was when the dialog goes.
 */
export default function ConfirmDialog({ title, children, confirmLabel, cancelLabel, onConfirm, onCancel }) {
  const titleId = useId();
  const bodyId = useId();
  const box = useRef(null);
  const safe = useRef(null);

  useEffect(() => {
    safe.current?.focus();
  }, []);

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onCancel();
      return;
    }
    if (event.key !== 'Tab' || !box.current) return;
    const stops = Array.from(box.current.querySelectorAll('button:not([disabled])'));
    if (stops.length === 0) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    const active = window.document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <>
      <div
        data-testid="confirm-backdrop"
        className="fixed inset-0 z-[60] bg-black/50"
        onClick={onCancel}
        aria-hidden="true"
      />
      <div
        ref={box}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={handleKeyDown}
        className="fixed inset-x-4 top-[15%] z-[70] mx-auto max-w-md max-h-[80vh] overflow-y-auto rounded-xl bg-white p-5 shadow-2xl"
      >
        <h2 id={titleId} className="text-lg font-semibold text-gray-900">{title}</h2>
        <div id={bodyId} className="mt-2 text-sm leading-relaxed text-gray-700 [overflow-wrap:anywhere]">{children}</div>
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <button
            ref={safe}
            type="button"
            onClick={onCancel}
            className="min-h-[44px] px-4 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="min-h-[44px] px-4 rounded-lg bg-red-700 text-sm font-medium text-white hover:bg-red-800"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </>
  );
}
