// @vitest-environment jsdom
import React from 'react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import CitationTypeGuide, { ConfidenceNote, RuleLabel, renderTemplate } from '../CitationTypeGuide';
import { browseTypes } from '../../utils/localCitation';

// renderToString puts <!-- --> between adjacent text nodes ("Rule <!-- -->10.3"), which
// would hide the text from a plain substring check.
const html = (node) => renderToString(node).replace(/<!-- -->/g, '');

describe('CitationTypeGuide', () => {
  it('renders every family and every type, in both styles, without throwing', () => {
    ['law_review', 'practitioner'].forEach((style) => {
      const out = html(<CitationTypeGuide style={style} />);
      browseTypes(style).forEach((family) => {
        expect(out).toContain(family.label);
        family.types.forEach((t) => expect(out).toContain(t.label));
      });
    });
  });

  it('opens a type when asked and shows its fields with verified rules', () => {
    const out = html(<CitationTypeGuide style="law_review" defaultOpenId="agency_report" />);
    expect(out).toContain('The finished shape');
    expect(out).toContain('Rule 15.1');
    expect(out).toContain('Format well established');
  });

  it('says plainly when a type is guidance only', () => {
    const out = html(<CitationTypeGuide style="law_review" defaultOpenId="state_statute" />);
    expect(out).toContain('Guidance only');
    expect(out).toContain('Check this format against your Bluebook');
  });

  it('carries the edition caveat', () => {
    expect(html(<CitationTypeGuide style="law_review" />)).toContain('21st edition');
  });
});

describe('the rule label and the guide rows fit a phone', () => {
  const RULE = { number: '15', title: 'Books, Reports, and Other Nonperiodic Materials' };

  const parse = (node) => {
    const holder = document.createElement('div');
    holder.innerHTML = renderToString(node);
    return holder;
  };

  // jsdom has no layout, so this is structural; the browser check is in the Playwright script.
  it('keeps "Rule N" in one piece and lets the title wrap, even inside a word if it must', () => {
    const label = parse(<RuleLabel rule={RULE} />).firstElementChild;
    const [number, title] = [...label.children].length ? [label.firstElementChild, label.lastElementChild] : [];
    expect(number.className).toContain('whitespace-nowrap');
    expect(number.textContent).toBe('Rule 15');
    expect(title.textContent).toContain('Books, Reports, and Other Nonperiodic Materials');
    expect(title.className).not.toContain('whitespace-nowrap');
    expect(label.className).not.toContain('whitespace-nowrap');
    expect(label.className).toContain('[overflow-wrap:anywhere]');
    expect(label.className).toContain('min-w-0');
    expect(label.className).toContain('max-w-full');
  });

  it('no part of the title is on a line that cannot break', () => {
    const label = parse(<RuleLabel rule={{ number: '18', title: 'x'.repeat(70) }} />).firstElementChild;
    const unbreakable = [...label.querySelectorAll('*')].filter((el) => el.className.includes('whitespace-nowrap'));
    expect(unbreakable.map((el) => el.textContent)).toEqual(['Rule 18']);
  });

  it('every row of the guide, and every open item, can shrink to the width of the phone', () => {
    const out = parse(<CitationTypeGuide style="law_review" defaultOpenId="agency_report" />);
    out.querySelectorAll('button[aria-expanded]').forEach((row) => {
      expect(row.className).toContain('min-h-[44px]');
      expect(row.firstElementChild.className).toContain('min-w-0');
    });
    const nowrap = [...out.querySelectorAll('[class*="whitespace-nowrap"]')].map((el) => el.textContent);
    expect(nowrap.length).toBeGreaterThan(0);
    nowrap.forEach((text) => expect(text).toMatch(/^Rule [\d.]+$/));
    out.querySelectorAll('li li .flex > span:first-child').forEach((name) => {
      expect(name.className).toContain('min-w-0');
    });
  });
});

describe('small pieces', () => {
  it('shows a rule with its title, or nothing', () => {
    expect(html(<RuleLabel rule={{ number: '10.3', title: 'Reporters and Services' }} />))
      .toContain('Rule 10.3');
    expect(html(<RuleLabel rule={null} />)).toBe('');
  });

  it('warns on any format that is not well established', () => {
    expect(html(<ConfidenceNote level="high" />)).toContain('well established');
    expect(html(<ConfidenceNote level="medium" />)).toContain('Check this format');
    expect(html(<ConfidenceNote level="low" />)).toContain('Check this format');
  });

  it('renders gaps as visible chips and italics as emphasis', () => {
    const out = html(<p>{renderTemplate('*Name*, [year]')}</p>);
    expect(out).toContain('<em>Name</em>');
    expect(out).toContain('year');
    expect(out).toContain('bg-amber-100');
  });
});
