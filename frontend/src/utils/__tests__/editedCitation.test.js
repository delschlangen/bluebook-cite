import { describe, expect, it } from 'vitest';
import { editedCitationText, editedFieldsDiffer } from '../editedCitation';
import { citation } from '../../test/fixtures';

describe('editedFieldsDiffer', () => {
  it('is false for the same fields, and ignores fields the editor does not change', () => {
    const before = citation(1);
    expect(editedFieldsDiffer(before, { ...before })).toBe(false);
    expect(editedFieldsDiffer(before, { ...before, confidence_score: 0.9, status: 'incomplete' })).toBe(false);
  });

  it('is true when an editable field changes, is cleared, or is filled in', () => {
    const before = citation(1);
    expect(editedFieldsDiffer(before, { ...before, year: 1955 })).toBe(true);
    expect(editedFieldsDiffer(before, { ...before, year: null })).toBe(true);
    expect(editedFieldsDiffer(before, { ...before, pincite: '490' })).toBe(true);
    expect(editedFieldsDiffer(before, { ...before, parties: ['Brown', 'Topeka'] })).toBe(true);
  });

  it('treats a missing field and an empty one as the same', () => {
    const before = citation(1);
    delete before.pincite;
    expect(editedFieldsDiffer(before, { ...before, pincite: null })).toBe(false);
  });
});

describe('editedCitationText: the card shows what was saved', () => {
  it('sets a case in Bluebook form from its saved fields, abbreviating the parties', () => {
    expect(editedCitationText({ ...citation(1), year: 1955 })).toBe('*Brown v. Bd. of Educ.*, 347 U.S. 1 (1955).');
  });

  it('a changed year, pincite and court appear in the text', () => {
    const text = editedCitationText({ ...citation(1), reporter: 'F.3d', court: '2d Cir.', year: 1999, pincite: '460' });
    expect(text).toContain('347 F.3d 1, 460');
    expect(text).toContain('(2d Cir. 1999)');
    expect(text).not.toContain('1954');
  });

  it('a cleared year leaves no year behind', () => {
    expect(editedCitationText({ ...citation(1), year: null })).not.toMatch(/19\d\d/);
  });

  it('falls back to the fields in order when the case is not complete enough to format', () => {
    const text = editedCitationText({ ...citation(1), parties: ['Brown'], volume: '347', reporter: 'U.S.', page: '483', year: 1954 });
    expect(text).toBe('Brown, 347 U.S. 483 (1954)');
  });

  it('writes a statute, an article, a book and a website from their fields', () => {
    expect(editedCitationText({ type: 'statute', raw_text: 'x', title_number: '17', code: 'U.S.C.', section: '107', year: 2018 })).toBe(
      '17 U.S.C. § 107 (2018)'
    );
    expect(editedCitationText({ type: 'law_review', raw_text: 'x', author: 'A. Author', title: 'On Things', volume: '12', journal: 'Yale L.J.', page: '34', year: 1999 })).toBe(
      'A. Author, On Things, 12 Yale L.J. 34 (1999)'
    );
    expect(editedCitationText({ type: 'book', raw_text: 'x', author: 'A. Author', title: 'The Book', year: 2001 })).toBe(
      'A. Author, The Book (2001)'
    );
    expect(editedCitationText({ type: 'website', raw_text: 'x', author: 'A', title: 'T', url: 'https://example.com' })).toBe(
      'A, T, https://example.com'
    );
  });

  it('shows the text as found when the type has nothing to edit, or every field was cleared', () => {
    expect(editedCitationText({ type: 'other', raw_text: 'Id.' })).toBe('Id.');
    expect(editedCitationText({ type: 'book', raw_text: 'Original text' })).toBe('Original text');
  });
});
