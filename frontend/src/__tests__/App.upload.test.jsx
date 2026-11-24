// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { act, fireEvent, screen } from '@testing-library/react';
import { MB, chooseFile, fileInput, file, findResults, renderApp, results, setup, tab, tick, visible } from './harness';
import { deferred, json, networkError } from '../test/fakeServer';
import { analysisBody, many, uploadBody } from '../test/fixtures';

const zone = () => screen.getByTestId('dropzone');
const drop = (...files) => fireEvent.drop(zone(), { dataTransfer: { files } });
const note = () => screen.queryByTestId('upload-notice');
const cancel = (user) => user.click(screen.getByRole('button', { name: 'Cancel' }));

describe('only one upload can be in flight, and what happens to the others is said', () => {
  const ctx = setup();

  it('a second file dropped while one is going up is ignored, with a line saying so', async () => {
    const pending = deferred();
    ctx.server.on('/api/upload', () => pending.promise);
    renderApp();
    await ctx.user.click(tab('Check a document'));
    drop(file('first.txt'));
    await screen.findByText('Uploading 1 KB...');

    drop(file('second.txt'));
    await tick();
    expect(ctx.server.count('/api/upload')).toBe(1);
    expect(note().textContent).toBe(
      'A file is already uploading, so the one you just added was ignored. Cancel the upload first if you want to use a different file.'
    );
  });

  it('when several files are dropped together, uses the first and says that the others were not used', async () => {
    renderApp();
    await ctx.user.click(tab('Check a document'));
    // The upload ends at once here, so look at what was sent and then at the line shown.
    const pending = deferred();
    ctx.server.on('/api/upload', () => pending.promise);
    drop(file('a.txt'), file('b.txt'), file('c.txt'));
    await screen.findByText('Uploading 1 KB...');
    expect(ctx.server.count('/api/upload')).toBe(1);
    expect(ctx.server.callsTo('/api/upload')[0].body.get('file').name).toBe('a.txt');
    expect(note().textContent).toBe(
      'Only one file is checked at a time, so only a.txt was used. The other 2 files were ignored.'
    );
  });

  it('says "file was", not "files were", for exactly two', async () => {
    ctx.server.on('/api/upload', () => new Promise(() => {}));
    renderApp();
    await ctx.user.click(tab('Check a document'));
    drop(file('a.txt'), file('b.txt'));
    await screen.findByTestId('upload-notice');
    expect(note().textContent).toContain('The other 1 file was ignored.');
  });

  it('says nothing about extra files when one file is chosen', async () => {
    ctx.server.on('/api/upload', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    expect(note()).toBeNull();
  });

  it('the note does not outlive the upload: it is gone when the results are shown and the person starts over', async () => {
    renderApp();
    await ctx.user.click(tab('Check a document'));
    drop(file('a.txt'), file('b.txt'));
    await findResults();
    await ctx.user.click(screen.getByRole('button', { name: 'Upload New Document' }));
    expect(note()).toBeNull();
  });
});

describe('Cancel', () => {
  const ctx = setup();

  it('is there while a file is going up, and aborts the request', async () => {
    ctx.server.on('/api/upload', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    const [call] = ctx.server.callsTo('/api/upload');
    expect(call.signal.aborted).toBe(false);

    await cancel(ctx.user);
    expect(call.signal.aborted).toBe(true);
    expect(screen.queryByText('Uploading 1 KB...')).toBeNull();
    expect(note().textContent).toBe('Upload cancelled. Choose the file again to start over.');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('is not there when nothing is uploading', async () => {
    renderApp();
    await ctx.user.click(tab('Check a document'));
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('means an answer that arrives later is ignored: it does not open the results', async () => {
    const pending = deferred();
    ctx.server.on('/api/upload', () => pending.promise, { ignoreAbort: true });
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    await cancel(ctx.user);

    await act(async () => {
      pending.resolve(json(uploadBody({ filename: 'late.txt' })));
    });
    await tick();
    expect(ctx.server.count('/api/analyze')).toBe(0);
    expect(results()).toBeNull();
    expect(screen.queryByText('Analyzing citations...')).toBeNull();
    expect(visible(tab('Check a document'))).toBe(true);
  });

  it('means a failure that arrives later is ignored too', async () => {
    const pending = deferred();
    ctx.server.on('/api/upload', () => pending.promise, { ignoreAbort: true });
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    await cancel(ctx.user);

    await act(async () => {
      pending.resolve(json({ detail: 'The PDF is encrypted.' }, 400));
    });
    await tick();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('lets a newer file through, and the older file never replaces its results', async () => {
    const older = deferred();
    ctx.server
      .sequence('/api/upload', [() => older.promise, () => json(uploadBody({ document_id: 'doc-B', filename: 'b.txt' }))], {
        ignoreAbort: true,
      })
      .on('/api/analyze', () => json(analysisBody({ citations: many(3) })));
    renderApp();
    await chooseFile(ctx, file('a.txt'));
    await screen.findByText('Uploading 1 KB...');
    await cancel(ctx.user);
    await chooseFile(ctx, file('b.txt'), { open: false });
    await findResults();
    expect(screen.getByText('b.txt')).toBeTruthy();

    await act(async () => {
      older.resolve(json(uploadBody({ document_id: 'doc-A', filename: 'a.txt' })));
    });
    await tick();
    expect(screen.getByText('b.txt')).toBeTruthy();
    expect(screen.queryByText('a.txt')).toBeNull();
    expect(ctx.server.count('/api/analyze')).toBe(1);
  });
});

describe('an upload that was cancelled cannot disturb the one that replaced it', () => {
  const ctx = setup();

  it('when the old one finally ends, the new one still shows as uploading and still refuses a third file', async () => {
    const older = deferred();
    const newer = deferred();
    ctx.server.sequence('/api/upload', [() => older.promise, () => newer.promise], { ignoreAbort: true });
    renderApp();
    await chooseFile(ctx, file('a.txt'));
    await screen.findByText('Uploading 1 KB...');
    await cancel(ctx.user);
    await ctx.user.upload(fileInput(), file('b.txt'));
    await screen.findByText('Uploading 1 KB...');
    expect(ctx.server.count('/api/upload')).toBe(2);

    await act(async () => {
      older.resolve(json({ detail: 'The PDF is encrypted.' }, 400));
    });
    await tick();
    expect(screen.getByText('Uploading 1 KB...')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();

    drop(file('c.txt'));
    await tick();
    expect(ctx.server.count('/api/upload')).toBe(2);
    expect(note().textContent).toContain('A file is already uploading');

    await act(async () => {
      newer.resolve(json(uploadBody({ filename: 'b.txt' })));
    });
    await findResults();
    expect(screen.getByText('b.txt')).toBeTruthy();
  });
});

describe('leaving the upload panel while a file is going up', () => {
  const ctx = setup();

  it('cannot be done: the other mode is disabled until the upload is cancelled or finishes', async () => {
    ctx.server.on('/api/upload', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    expect(tab('Fix a citation').disabled).toBe(true);
    expect(tab('Check a document').disabled).toBe(false);
    expect(screen.getByText('A file is uploading. Cancel the upload to switch.')).toBeTruthy();

    await cancel(ctx.user);
    expect(tab('Fix a citation').disabled).toBe(false);
    expect(screen.queryByText('A file is uploading. Cancel the upload to switch.')).toBeNull();
  });

  it('keeps a citation pasted in the Fix tab through an upload that is cancelled, and through one that finishes', async () => {
    renderApp();
    const box = () => screen.getByLabelText('Citation to repair');
    await ctx.user.type(box(), 'Moody v. NetChoice');
    await ctx.user.click(tab('Check a document'));
    expect(visible(box())).toBe(false);

    const pending = deferred();
    ctx.server.on('/api/upload', () => pending.promise);
    await ctx.user.upload(fileInput(), file());
    await screen.findByText('Uploading 1 KB...');
    await cancel(ctx.user);
    await ctx.user.click(tab('Fix a citation'));
    expect(visible(box())).toBe(true);
    expect(box().value).toBe('Moody v. NetChoice');

    // Now one that goes through: results, then back to the start.
    ctx.server.on('/api/upload', () => json(uploadBody()));
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(fileInput(), file());
    await findResults();
    await ctx.user.click(screen.getByRole('button', { name: 'Upload New Document' }));
    await ctx.user.click(tab('Fix a citation'));
    expect(box().value).toBe('Moody v. NetChoice');
  });

  it('a file chosen or dropped while one is going up is not sent: the input is disabled and the drop is ignored', async () => {
    ctx.server.on('/api/upload', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    // Even a file chosen by some other route while one is in flight is not sent.
    await ctx.user.upload(fileInput(), file('other.txt')).catch(() => {});
    drop(file('other.txt'));
    await tick();
    expect(ctx.server.count('/api/upload')).toBe(1);
  });
});

describe('what is refused before anything is sent', () => {
  const ctx = setup();

  it('a file over the limit, with a size that is above the limit it is compared with', async () => {
    renderApp();
    await chooseFile(ctx, file('big.docx', 10 * MB + 30000));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'This file is 10.1 MB. The limit is 10 MB. Split the document at a chapter or section boundary and ' +
        'check the parts one at a time, or export it again at a smaller size.'
    );
    expect(ctx.server.count('/api/upload')).toBe(0);
  });

  it('a file of exactly the limit is sent', async () => {
    renderApp();
    await chooseFile(ctx, file('edge.pdf', 10 * MB));
    await findResults();
    expect(ctx.server.count('/api/upload')).toBe(1);
  });

  it('a file type that is known not to work, with what to do instead', async () => {
    renderApp();
    await chooseFile(ctx, file('brief.doc'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Old-format Word (.doc) files are not supported. In Word, choose Save As and pick .docx, or export a PDF.'
    );
    expect(ctx.server.count('/api/upload')).toBe(0);
  });

  it('a file of a type the browser does not report is still sent, and the server decides', async () => {
    renderApp();
    await chooseFile(ctx, new File(['x'], 'scan-from-icloud', { type: '' }));
    await findResults();
    expect(ctx.server.count('/api/upload')).toBe(1);
  });

  it('a refusal is cleared by the next file that is accepted', async () => {
    renderApp();
    await chooseFile(ctx, file('brief.doc'));
    await screen.findByRole('alert');
    await ctx.user.upload(fileInput(), file('ok.txt'));
    await findResults();
    await ctx.user.click(screen.getByRole('button', { name: 'Upload New Document' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('uses the limit the server reported, in the box and in the check', async () => {
    ctx.server.on('/health', () =>
      json({ boot_id: 'boot-A', limits: { max_upload_mb: 25, max_pdf_pages: 150, approx_max_words: 100000, approx_max_pages: 140 } })
    );
    renderApp();
    await ctx.user.click(tab('Check a document'));
    await screen.findByText(/^Up to 25 MB\./);
    expect(screen.getByTestId('upload-limits').textContent).toContain('PDFs up to 150 pages');
    await ctx.user.upload(fileInput(), file('twelve.pdf', 12 * MB));
    await findResults();
    expect(ctx.server.count('/api/upload')).toBe(1);
  });

  it('shows the limits in text that is dark enough to read', async () => {
    renderApp();
    await ctx.user.click(tab('Check a document'));
    expect(screen.getByTestId('upload-limits').className).toContain('text-gray-600');
  });
});

describe('what a failed upload says, and what the person can do next', () => {
  const ctx = setup();

  it('shows what the server said, in an alert', async () => {
    ctx.server.on('/api/upload', () =>
      json({ detail: 'This PDF has 500 pages, which is over the 400-page limit. Split it into parts of 400 pages or fewer.' }, 413)
    );
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'This PDF has 500 pages, which is over the 400-page limit. Split it into parts of 400 pages or fewer.'
    );
  });

  it('puts a refusal with no explanation in plain words', async () => {
    ctx.server.on('/api/upload', () => json({ detail: [{ msg: 'field required' }] }, 422));
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The server could not use what this page sent.');
    expect(alert.textContent).not.toContain('Server returned');
  });

  it('can choose the same file again after a failure', async () => {
    const same = file('same.txt');
    ctx.server.sequence('/api/upload', [() => json({ detail: 'Reading this file failed.' }, 400), () => json(uploadBody())]);
    renderApp();
    await chooseFile(ctx, same);
    await screen.findByRole('alert');
    expect(fileInput().value).toBe('');
    await ctx.user.upload(fileInput(), same);
    await findResults();
    expect(ctx.server.count('/api/upload')).toBe(2);
  });

  it('with no response at all, asks the server what happened before blaming it', async () => {
    ctx.server.on('/api/upload', () => {
      throw networkError();
    });
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(ctx.server.count('/health')).toBe(2);
    expect(alert.textContent).toBe(
      'The upload failed: the server is running, but this request did not complete. It may have taken ' +
        'too long on a slow connection, or the connection dropped. Try again, and if it keeps happening ' +
        'try a smaller file.'
    );
  });

  it('says the server restarted when the id changed during the upload', async () => {
    ctx.server.on('/api/upload', () => {
      ctx.bootId = 'boot-B';
      throw networkError();
    });
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The upload failed: the server restarted while working on your document.');
  });
});
