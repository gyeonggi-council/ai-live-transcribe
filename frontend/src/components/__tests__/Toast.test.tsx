import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ToastProvider, useToast } from '../Toast';

// Test component to trigger toast
function TestTrigger() {
  const { showToast } = useToast();

  return (
    <div>
      <button onClick={() => showToast('success', 'Success message')}>
        Show Success
      </button>
      <button onClick={() => showToast('error', 'Error message')}>
        Show Error
      </button>
      <button onClick={() => showToast('warning', 'Warning message')}>
        Show Warning
      </button>
      <button onClick={() => showToast('info', 'Info message')}>
        Show Info
      </button>
    </div>
  );
}

describe('Toast', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  describe('variants', () => {
    it('renders success toast with KRDS success accent', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Success'));

      const toast = screen.getByText('Success message');
      expect(toast).toBeInTheDocument();
      expect(toast.closest('[role="alert"]')).toHaveClass('bg-white');
      expect(toast.closest('[role="alert"]')).toHaveClass('border-l-success');
    });

    it('renders error toast with KRDS error accent', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Error'));

      const toast = screen.getByText('Error message');
      expect(toast).toBeInTheDocument();
      expect(toast.closest('[role="alert"]')).toHaveClass('bg-white');
      expect(toast.closest('[role="alert"]')).toHaveClass('border-l-error');
    });

    it('renders warning toast with KRDS warning accent', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Warning'));

      const toast = screen.getByText('Warning message');
      expect(toast).toBeInTheDocument();
      expect(toast.closest('[role="alert"]')).toHaveClass('bg-white');
      expect(toast.closest('[role="alert"]')).toHaveClass('border-l-warning');
    });

    it('renders info toast with KRDS info accent', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Info'));

      const toast = screen.getByText('Info message');
      expect(toast).toBeInTheDocument();
      expect(toast.closest('[role="alert"]')).toHaveClass('bg-white');
      expect(toast.closest('[role="alert"]')).toHaveClass('border-l-info');
    });
  });

  describe('auto dismiss', () => {
    it('auto dismisses after 3 seconds', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Success'));
      expect(screen.getByText('Success message')).toBeInTheDocument();

      act(() => {
        jest.advanceTimersByTime(3000);
      });

      await waitFor(() => {
        expect(screen.queryByText('Success message')).not.toBeInTheDocument();
      });
    });
  });

  describe('positioning', () => {
    it('is positioned at bottom-right', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Success'));

      const toastContainer = screen.getByRole('alert').parentElement;
      expect(toastContainer).toHaveClass('fixed');
      expect(toastContainer).toHaveClass('bottom-4');
      expect(toastContainer).toHaveClass('right-4');
    });
  });

  describe('accessibility', () => {
    it('has role="alert" for screen readers', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Success'));

      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  describe('useToast hook', () => {
    it('throws error when used outside ToastProvider', () => {
      // Suppress console.error for this test
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

      function TestComponent() {
        useToast();
        return null;
      }

      expect(() => render(<TestComponent />)).toThrow(
        'useToast must be used within a ToastProvider'
      );

      consoleSpy.mockRestore();
    });
  });

  describe('manual close', () => {
    it('closes toast when close button is clicked', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(
        <ToastProvider>
          <TestTrigger />
        </ToastProvider>
      );

      await user.click(screen.getByText('Show Success'));
      expect(screen.getByText('Success message')).toBeInTheDocument();

      const closeButton = screen.getByRole('button', { name: 'Close' });
      await user.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText('Success message')).not.toBeInTheDocument();
      });
    });
  });
});
