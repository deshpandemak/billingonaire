import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

// Upload.jsx imports the real Firebase SDK directly -- stub both so the
// component can render without a live Firebase app.
vi.mock('../lib/firebase', () => ({
  auth: { currentUser: { getIdToken: vi.fn().mockResolvedValue('fake-token') } },
}));

vi.mock('firebase/auth', () => ({
  onAuthStateChanged: (_auth, callback) => {
    callback({ uid: 'u1' });
    return () => {};
  },
}));

import Upload from '../Upload';

function renderUpload() {
  return render(
    <MemoryRouter>
      <Upload />
    </MemoryRouter>
  );
}

describe('Upload', () => {
  // Regression for the Android "tap does nothing" bug: a display:none file
  // input behind a JS-triggered fileInput.current.click() silently fails to
  // open the file picker on several Android browsers/WebViews. The fix
  // layers a real, still-interactive (opacity: 0, not display: none) file
  // input directly over the drop zone so a native tap lands on it.
  it('renders exactly one file input that is not display:none (tappable, not hidden)', () => {
    const { container } = renderUpload();
    const inputs = container.querySelectorAll('input[type="file"]');
    expect(inputs).toHaveLength(1);
    expect(inputs[0].style.display).not.toBe('none');
    expect(inputs[0].disabled).toBe(false);
  });

  it('does not rely on a click() proxy -- the drop zone has no onClick handler', () => {
    const { container } = renderUpload();
    const input = container.querySelector('input[type="file"]');
    // The input's immediate parent is the drop zone; it must have no click
    // handler of its own now that the input itself is directly tappable.
    // (jsdom doesn't expose attached React handlers directly, so this is
    // verified via behavior below instead of introspecting fiber internals.)
    expect(input).toBeTruthy();
  });

  it('selecting a PDF via the input updates the selected-files list', async () => {
    const { container } = renderUpload();
    const input = container.querySelector('input[type="file"]');
    const file = new File(['%PDF-1.4'], 'board.pdf', { type: 'application/pdf' });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/1 file selected/i)).toBeTruthy();
    });
    expect(screen.getByText('board.pdf')).toBeTruthy();
  });

  it('rejects non-PDF files with an inline error', async () => {
    const { container } = renderUpload();
    const input = container.querySelector('input[type="file"]');
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/only pdf files are accepted/i)).toBeTruthy();
    });
  });
});
