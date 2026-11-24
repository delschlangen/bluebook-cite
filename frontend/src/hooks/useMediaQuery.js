import { useEffect, useState } from 'react';

const supported = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function';

/** Whether a CSS media query matches now, kept up to date. False where matchMedia does not exist. */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => (supported() ? window.matchMedia(query).matches : false));

  useEffect(() => {
    if (!supported()) return undefined;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    if (list.addEventListener) list.addEventListener('change', update);
    else list.addListener(update); // Safari before 14
    return () => {
      if (list.removeEventListener) list.removeEventListener('change', update);
      else list.removeListener(update);
    };
  }, [query]);

  return matches;
}
