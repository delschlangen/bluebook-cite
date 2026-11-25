import React from 'react';
import { safeHttpUrl } from '../utils/safeUrl';

/**
 * A link to somewhere outside the page, for an address the server (or anyone) supplied. It opens
 * in a new tab without handing that tab this page (`noopener noreferrer`), and it is not drawn at
 * all unless the address is an http or https one: showing nothing is better than a link that
 * runs a script. Other props (className, aria-label) go to the <a>.
 */
export default function ExternalLink({ href, children, ...props }) {
  const safe = safeHttpUrl(href);
  if (!safe) return null;
  return (
    <a {...props} href={safe} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
