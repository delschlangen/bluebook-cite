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
