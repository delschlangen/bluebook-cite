// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { rovingKeys } from '../roving';

/** A strip of controls with the given roles, states and a handler on the strip. Returns the items. */
function strip(items, options) {
  const group = document.createElement('div');
  items.forEach(({ disabled, aria, role = 'tab' }, i) => {
    const el = document.createElement('button');
    el.setAttribute('role', role);
    el.textContent = `item ${i}`;
    if (disabled) el.disabled = true;
    if (aria) el.setAttribute('aria-disabled', 'true');
    el.addEventListener('click', () => { el.dataset.chosen = 'yes'; });
    group.appendChild(el);
  });
  const handler = rovingKeys(options);
  group.addEventListener('keydown', (e) => handler({ ...e, key: e.key, shiftKey: e.shiftKey, target: e.target, currentTarget: group, preventDefault: () => e.preventDefault() }));
  document.body.appendChild(group);
  return { group, els: [...group.children] };
}
const press = (el, key) => fireEvent.keyDown(el, { key });

describe('rovingKeys', () => {
  it('moves to the next and the previous, and wraps at both ends, focusing and choosing the one it reaches', () => {
    const { els } = strip([{}, {}, {}]);
    els[0].focus();
    press(els[0], 'ArrowRight');
    expect(document.activeElement).toBe(els[1]);
    expect(els[1].dataset.chosen).toBe('yes');
    press(els[1], 'ArrowRight');
    press(els[2], 'ArrowRight');
    expect(document.activeElement).toBe(els[0]); // wrapped forwards
    press(els[0], 'ArrowLeft');
    expect(document.activeElement).toBe(els[2]); // wrapped backwards
  });

  it('Home and End go to the first and the last, from wherever it is', () => {
    const { els } = strip([{}, {}, {}, {}]);
    els[1].focus();
    press(els[1], 'End');
    expect(document.activeElement).toBe(els[3]);
    press(els[3], 'Home');
    expect(document.activeElement).toBe(els[0]);
    els[2].focus();
    press(els[2], 'Home');
    expect(document.activeElement).toBe(els[0]);
    els[1].focus();
    press(els[1], 'End');
    expect(document.activeElement).toBe(els[3]);
  });

  it('skips a control that is disabled, or aria-disabled, in either direction', () => {
    const { els } = strip([{}, { disabled: true }, { aria: true }, {}]);
    els[0].focus();
    press(els[0], 'ArrowRight');
    expect(document.activeElement).toBe(els[3]);
    press(els[3], 'ArrowLeft');
    expect(document.activeElement).toBe(els[0]);
    expect(els[1].dataset.chosen).toBeUndefined();
    expect(els[2].dataset.chosen).toBeUndefined();
  });

  it('does nothing when fewer than two controls can be chosen', () => {
    const { els } = strip([{ disabled: true }, {}]);
    els[1].focus();
    press(els[1], 'ArrowRight');
    expect(document.activeElement).toBe(els[1]);
    expect(els[1].dataset.chosen).toBeUndefined();
  });

  it('keeps the page from scrolling for a key it uses, and leaves every other key alone', () => {
    const { els } = strip([{}, {}]);
    els[0].focus();
    expect(press(els[0], 'ArrowRight')).toBe(false); // default prevented
    expect(press(els[1], 'Home')).toBe(false);
    for (const key of ['a', 'Enter', ' ', 'Tab', 'Escape', 'PageDown']) expect(press(els[1], key), key).toBe(true);
  });

  it('a strip of tabs answers only the left and right arrows; radios answer up and down too', () => {
    const tabs = strip([{}, {}, {}]);
    tabs.els[0].focus();
    expect(press(tabs.els[0], 'ArrowDown')).toBe(true);
    expect(press(tabs.els[0], 'ArrowUp')).toBe(true);
    expect(document.activeElement).toBe(tabs.els[0]);
    const radios = strip([{ role: 'radio' }, { role: 'radio' }, { role: 'radio' }], { vertical: true });
    radios.els[0].focus();
    expect(press(radios.els[0], 'ArrowDown')).toBe(false);
    expect(document.activeElement).toBe(radios.els[1]);
    press(radios.els[1], 'ArrowUp');
    expect(document.activeElement).toBe(radios.els[0]);
  });

  it('ignores a key pressed on something that is not one of the controls', () => {
    const { group, els } = strip([{}, {}]);
    const other = document.createElement('input');
    group.appendChild(other);
    other.focus();
    expect(press(other, 'ArrowRight')).toBe(true);
    expect(els[0].dataset.chosen).toBeUndefined();
  });
});
