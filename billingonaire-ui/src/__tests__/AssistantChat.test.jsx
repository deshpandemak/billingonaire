import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../lib/api', () => ({
  authenticatedFetchJSON: vi.fn(),
}));

import * as api from '../lib/api';
import AssistantChat from '../components/AssistantChat';

describe('AssistantChat', () => {
  it('starts closed, showing only the launcher button', () => {
    render(<AssistantChat />);
    expect(screen.getByLabelText('Open assistant')).toBeTruthy();
    expect(screen.queryByLabelText('Billingonaire assistant')).toBeNull();
  });

  it('opens the panel when the launcher is clicked', () => {
    render(<AssistantChat />);
    fireEvent.click(screen.getByLabelText('Open assistant'));
    expect(screen.getByLabelText('Billingonaire assistant')).toBeTruthy();
    expect(screen.getByPlaceholderText('Ask a question…')).toBeTruthy();
  });

  it('sends a question and renders the answer', async () => {
    api.authenticatedFetchJSON.mockResolvedValueOnce({ answer: 'You have 3 cases.', tool_used: 'get_queue_status' });
    render(<AssistantChat />);
    fireEvent.click(screen.getByLabelText('Open assistant'));

    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), {
      target: { value: 'How many cases need attention?' },
    });
    fireEvent.click(screen.getByText('Send'));

    expect(screen.getByText('How many cases need attention?')).toBeTruthy();
    await waitFor(() => screen.getByText('You have 3 cases.'));

    expect(api.authenticatedFetchJSON).toHaveBeenCalledWith(
      '/assistant/ask',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ question: 'How many cases need attention?', history: [] }),
      })
    );
  });

  it('sends prior turns as history on the next question', async () => {
    api.authenticatedFetchJSON
      .mockResolvedValueOnce({ answer: 'First answer.', tool_used: null })
      .mockResolvedValueOnce({ answer: 'Second answer.', tool_used: null });
    render(<AssistantChat />);
    fireEvent.click(screen.getByLabelText('Open assistant'));

    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: 'first question' } });
    fireEvent.click(screen.getByText('Send'));
    await waitFor(() => screen.getByText('First answer.'));

    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: 'second question' } });
    fireEvent.click(screen.getByText('Send'));
    await waitFor(() => screen.getByText('Second answer.'));

    const secondCallBody = JSON.parse(api.authenticatedFetchJSON.mock.calls[1][1].body);
    expect(secondCallBody.history).toEqual([
      { role: 'user', text: 'first question' },
      { role: 'assistant', text: 'First answer.' },
    ]);
  });

  it('shows an inline error without crashing when the request fails', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('API call failed: 502 Bad Gateway'));
    render(<AssistantChat />);
    fireEvent.click(screen.getByLabelText('Open assistant'));

    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: 'anything' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => screen.getByText(/502 Bad Gateway/));
    expect(screen.getByLabelText('Billingonaire assistant')).toBeTruthy();
  });

  it('disappears entirely once the backend reports it is not configured (501)', async () => {
    api.authenticatedFetchJSON.mockRejectedValueOnce(new Error('API call failed: 501 Not Implemented'));
    const { container } = render(<AssistantChat />);
    fireEvent.click(screen.getByLabelText('Open assistant'));

    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: 'anything' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => expect(container.firstChild).toBeNull());
  });

  it('does not send an empty question', () => {
    render(<AssistantChat />);
    fireEvent.click(screen.getByLabelText('Open assistant'));
    fireEvent.click(screen.getByText('Send'));
    expect(api.authenticatedFetchJSON).not.toHaveBeenCalled();
  });
});
