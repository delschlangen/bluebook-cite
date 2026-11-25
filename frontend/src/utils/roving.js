// Tabs and radio buttons are one stop in the Tab order: the selected one. The arrow keys move
// between them (and Home and End jump to the first and last), as every tab strip and radio group
// does. Moving to one chooses it, which is what a click on it does, so this clicks it.

const NEXT = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

/**
 * `onKeyDown` for the element that holds the tabs or radios. `vertical` also answers ArrowUp and
 * ArrowDown, as a radio group does; a strip of tabs only answers ArrowLeft and ArrowRight.
 */
export function rovingKeys({ vertical = false } = {}) {
  return (event) => {
    const { key } = event;
    const step = NEXT[key];
    const horizontal = key === 'ArrowLeft' || key === 'ArrowRight';
    if (!(key === 'Home' || key === 'End' || (step && (horizontal || vertical)))) return;
    const current = event.target.closest?.('[role="tab"], [role="radio"]');
    if (!current) return;
    const items = [...event.currentTarget.querySelectorAll('[role="tab"], [role="radio"]')].filter(
      (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true'
    );
    const from = items.indexOf(current);
    if (from < 0 || items.length < 2) return;
    let to;
    if (key === 'Home') to = 0;
    else if (key === 'End') to = items.length - 1;
    else to = (from + step + items.length) % items.length;
    event.preventDefault();
    items[to].focus();
    items[to].click();
  };
}
