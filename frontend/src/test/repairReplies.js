// /api/repair answers shaped like the real server's (copied from what it sends), for the tests
// of the Fix a citation page and of the check on what comes back.

const RULE = { number: '10.3', title: 'Reporters and Services' };

export const incompleteReply = (extra = {}) => ({
  input: 'Moody v. NetChoice',
  status: 'incomplete',
  citation_type: 'case',
  parsed: { parties: ['Moody', 'NetChoice'] },
  missing: ['volume', 'reporter', 'page', 'year'],
  missing_labels: ['volume number', 'reporter', 'first page', 'year'],
  missing_details: [
    { field: 'volume', label: 'volume number', rule: '10.3', why: 'The reporter volume the case starts in.', display_rule: RULE },
    { field: 'year', label: 'year', rule: '10.5', why: 'The year of decision.', display_rule: null },
  ],
  template: '*Moody v. NetChoice*, [volume number] [reporter] [first page] ([year]).',
  kind: null,
  kind_label: null,
  format_confidence: null,
  style: 'law_review',
  rule_note: 'Rule numbers follow the 21st edition.',
  formatted: null,
  confidence: null,
  source: null,
  verify_url: null,
  candidates: [],
  notes: ['No matching record was found in CourtListener. That does not mean there is no such record.'],
  ...extra,
});

export const resolvedReply = (extra = {}) => ({
  input: 'Moody v. NetChoice',
  status: 'resolved',
  citation_type: 'case',
  parsed: { parties: ['Moody', 'NetChoice, LLC'], volume: '603', reporter: 'U.S.', page: '707', year: 2024 },
  missing: [],
  missing_labels: [],
  missing_details: [],
  template: '*Moody v. NetChoice, LLC*, 603 U.S. 707 (2024).',
  kind: null,
  kind_label: null,
  format_confidence: null,
  style: 'law_review',
  rule_note: null,
  formatted: '*Moody v. NetChoice, LLC*, 603 U.S. 707 (2024).',
  confidence: 0.95,
  source: 'CourtListener',
  verify_url: 'https://www.courtlistener.com/opinion/9999999/moody-v-netchoice-llc/',
  candidates: [],
  notes: ['Matched a record with a verification link.'],
  ...extra,
});

export const ambiguousReply = (extra = {}) => ({
  ...incompleteReply(),
  status: 'ambiguous',
  candidates: [
    {
      label: 'Moody v. NetChoice, LLC',
      court: 'Supreme Court',
      date: '2024-07-01',
      verify_url: 'https://www.courtlistener.com/opinion/1/moody-v-netchoice/',
    },
    {
      label: 'Moody v. NetChoice, LLC',
      court: 'Eleventh Circuit',
      date: '2022-05-23',
      verify_url: 'https://www.courtlistener.com/opinion/2/moody-v-netchoice/',
    },
  ],
  notes: ['More than one record matched, and none was confident enough to apply.'],
  ...extra,
});

export const unparseableReply = (extra = {}) => ({
  ...incompleteReply(),
  status: 'unparseable',
  citation_type: null,
  parsed: {},
  missing: [],
  missing_labels: [],
  missing_details: [],
  template: null,
  rule_note: null,
  notes: ['This does not look like a kind of citation this tool recognises yet.'],
  ...extra,
});
