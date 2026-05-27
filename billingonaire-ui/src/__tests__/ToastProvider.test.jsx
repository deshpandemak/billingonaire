import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ToastProvider, useToast } from '../components/ToastProvider';

const AddToastButton = ({ message = 'hello toast', type = 'success' }) => {
  const { addToast } = useToast();
  return <button onClick={() => addToast(message, type)}>Add Toast</button>;
};

describe('ToastProvider', () => {
  it('renders children without crashing', () => {
    render(
      <ToastProvider>
        <div data-testid="child">child content</div>
      </ToastProvider>
    );
    expect(screen.getByTestId('child')).toBeTruthy();
  });

  it('provides the addToast function via useToast hook', () => {
    render(
      <ToastProvider>
        <AddToastButton />
      </ToastProvider>
    );
    expect(screen.getByText('Add Toast')).toBeTruthy();
  });

  it('displays a toast message after addToast is called', () => {
    render(
      <ToastProvider>
        <AddToastButton message="Operation complete" />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Add Toast'));
    expect(screen.getByText('Operation complete')).toBeTruthy();
  });

  it('displays a toast for error type', () => {
    render(
      <ToastProvider>
        <AddToastButton message="Something went wrong" type="error" />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Add Toast'));
    const alert = screen.getByRole('alert');
    expect(alert.className).toContain('alert-danger');
  });

  it('displays a toast for info type', () => {
    render(
      <ToastProvider>
        <AddToastButton message="FYI info" type="info" />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Add Toast'));
    const alert = screen.getByRole('alert');
    expect(alert.className).toContain('alert-primary');
  });

  it('dismisses a toast when the close button is clicked', () => {
    render(
      <ToastProvider>
        <AddToastButton message="Dismiss me" />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Add Toast'));
    expect(screen.getByText('Dismiss me')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Dismiss'));
    expect(screen.queryByText('Dismiss me')).toBeNull();
  });

  it('useToast returns safe no-op fallback when used outside provider', () => {
    const SafeConsumer = () => {
      const { addToast } = useToast();
      addToast('this should not throw');
      return <div>safe</div>;
    };
    expect(() => render(<SafeConsumer />)).not.toThrow();
  });
});
