import { render, screen } from '@testing-library/react';

import Badge from '../Badge';

describe('Badge', () => {
  describe('variants', () => {
    it('renders live variant with pulse animation', () => {
      render(<Badge variant="live">Live</Badge>);

      const badge = screen.getByText('Live');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass('bg-danger/10');
      expect(badge).toHaveClass('text-danger');

      // Check for pulse indicator
      const pulseIndicator = badge.querySelector('.animate-live-pulse');
      expect(pulseIndicator).toBeInTheDocument();
    });

    it('renders success variant with KRDS success colors', () => {
      render(<Badge variant="success">Completed</Badge>);

      const badge = screen.getByText('Completed');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass('bg-success/10');
      expect(badge).toHaveClass('text-success');
    });

    it('renders warning variant with KRDS warning colors', () => {
      render(<Badge variant="warning">Processing</Badge>);

      const badge = screen.getByText('Processing');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass('bg-warning-bg/20');
      expect(badge).toHaveClass('text-warning-dark');
    });

    it('renders secondary variant with surface colors', () => {
      render(<Badge variant="secondary">VOD</Badge>);

      const badge = screen.getByText('VOD');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass('bg-surface-raised');
      expect(badge).toHaveClass('text-text-secondary');
    });
  });

  describe('styling', () => {
    it('has correct base styles', () => {
      render(<Badge variant="success">Test</Badge>);

      const badge = screen.getByText('Test');
      expect(badge).toHaveClass('inline-flex');
      expect(badge).toHaveClass('items-center');
      expect(badge).toHaveClass('px-2.5');
      expect(badge).toHaveClass('py-0.5');
      expect(badge).toHaveClass('rounded-full');
      expect(badge).toHaveClass('text-xs');
      expect(badge).toHaveClass('font-medium');
    });

    it('accepts additional className', () => {
      render(<Badge variant="success" className="custom-class">Test</Badge>);

      const badge = screen.getByText('Test');
      expect(badge).toHaveClass('custom-class');
    });
  });
});
