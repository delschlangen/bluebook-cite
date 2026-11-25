import React, { useEffect, useState } from 'react';

const DEFAULT_CLASS =
  'mb-6 min-h-[44px] px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium ' +
  'disabled:bg-gray-200 disabled:text-gray-700 disabled:cursor-not-allowed';

/**
 * Try again. When the server said how long to wait (a busy 503 with Retry-After), the button is
 * disabled and counts that down, so pressing it does not just be refused again.
 */
export default function RetryButton({ onRetry, waitSeconds, className = DEFAULT_CLASS }) {
  const wait = Number.isFinite(waitSeconds) && waitSeconds > 0 ? Math.ceil(waitSeconds) : 0;
  const [until] = useState(() => Date.now() + wait * 1000);
  const [left, setLeft] = useState(wait);

  useEffect(() => {
    if (!wait) return undefined;
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) clearInterval(timer);
    };
    const timer = setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [wait, until]);

  return (
    <button type="button" onClick={onRetry} disabled={left > 0} className={className}>
      {left > 0 ? `Try again in ${left} s` : 'Try again'}
    </button>
  );
}
