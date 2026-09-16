import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import Pagination from '../Pagination';

describe('Pagination', () => {
  const defaultProps = {
    currentPage: 1,
    totalPages: 5,
    onPageChange: jest.fn(),
  };

  beforeEach(() => {
    defaultProps.onPageChange.mockClear();
  });

  describe('Page Button Rendering', () => {
    it('renders all page buttons', () => {
      render(<Pagination {...defaultProps} />);

      // Should render page 1 to 5
      expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '2' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '3' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '4' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '5' })).toBeInTheDocument();
    });

    it('renders Previous and Next buttons', () => {
      render(<Pagination {...defaultProps} />);

      expect(screen.getByRole('button', { name: /이전/ })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /다음/ })).toBeInTheDocument();
    });

    it('renders navigation element with correct label', () => {
      render(<Pagination {...defaultProps} />);

      expect(screen.getByRole('navigation', { name: /페이지네이션/ })).toBeInTheDocument();
    });
  });

  describe('Current Page Highlight', () => {
    it('highlights current page button', () => {
      render(<Pagination {...defaultProps} currentPage={3} />);

      const currentPageButton = screen.getByRole('button', { name: '3' });
      expect(currentPageButton).toHaveClass('bg-primary');
      expect(currentPageButton).toHaveAttribute('aria-current', 'page');
    });

    it('non-current pages do not have highlight', () => {
      render(<Pagination {...defaultProps} currentPage={3} />);

      const otherPageButton = screen.getByRole('button', { name: '2' });
      expect(otherPageButton).not.toHaveClass('bg-primary');
      expect(otherPageButton).not.toHaveAttribute('aria-current', 'page');
    });
  });

  describe('Previous/Next Button Click', () => {
    it('calls onPageChange with previous page when Previous is clicked', async () => {
      const user = userEvent.setup();
      render(<Pagination {...defaultProps} currentPage={3} />);

      const prevButton = screen.getByRole('button', { name: /이전/ });
      await user.click(prevButton);

      expect(defaultProps.onPageChange).toHaveBeenCalledWith(2);
    });

    it('calls onPageChange with next page when Next is clicked', async () => {
      const user = userEvent.setup();
      render(<Pagination {...defaultProps} currentPage={3} />);

      const nextButton = screen.getByRole('button', { name: /다음/ });
      await user.click(nextButton);

      expect(defaultProps.onPageChange).toHaveBeenCalledWith(4);
    });
  });

  describe('Page Number Click', () => {
    it('calls onPageChange when page number is clicked', async () => {
      const user = userEvent.setup();
      render(<Pagination {...defaultProps} currentPage={1} />);

      const pageThreeButton = screen.getByRole('button', { name: '3' });
      await user.click(pageThreeButton);

      expect(defaultProps.onPageChange).toHaveBeenCalledWith(3);
    });

    it('does not call onPageChange when current page is clicked', async () => {
      const user = userEvent.setup();
      render(<Pagination {...defaultProps} currentPage={3} />);

      const currentPageButton = screen.getByRole('button', { name: '3' });
      await user.click(currentPageButton);

      expect(defaultProps.onPageChange).not.toHaveBeenCalled();
    });
  });

  describe('First Page - Previous Button Disabled', () => {
    it('disables Previous button on first page', () => {
      render(<Pagination {...defaultProps} currentPage={1} />);

      const prevButton = screen.getByRole('button', { name: /이전/ });
      expect(prevButton).toBeDisabled();
    });

    it('enables Previous button on non-first page', () => {
      render(<Pagination {...defaultProps} currentPage={2} />);

      const prevButton = screen.getByRole('button', { name: /이전/ });
      expect(prevButton).not.toBeDisabled();
    });
  });

  describe('Last Page - Next Button Disabled', () => {
    it('disables Next button on last page', () => {
      render(<Pagination {...defaultProps} currentPage={5} totalPages={5} />);

      const nextButton = screen.getByRole('button', { name: /다음/ });
      expect(nextButton).toBeDisabled();
    });

    it('enables Next button on non-last page', () => {
      render(<Pagination {...defaultProps} currentPage={4} totalPages={5} />);

      const nextButton = screen.getByRole('button', { name: /다음/ });
      expect(nextButton).not.toBeDisabled();
    });
  });

  describe('Single Page', () => {
    it('both Previous and Next are disabled on single page', () => {
      render(<Pagination {...defaultProps} currentPage={1} totalPages={1} />);

      const prevButton = screen.getByRole('button', { name: /이전/ });
      const nextButton = screen.getByRole('button', { name: /다음/ });

      expect(prevButton).toBeDisabled();
      expect(nextButton).toBeDisabled();
    });
  });

  describe('Many Pages - Ellipsis Display', () => {
    it('shows ellipsis for many pages', () => {
      render(<Pagination {...defaultProps} currentPage={5} totalPages={10} />);

      // Should show ellipsis (...) somewhere
      const ellipsis = screen.getAllByText('...');
      expect(ellipsis.length).toBeGreaterThan(0);
    });

    it('always shows first and last page', () => {
      render(<Pagination {...defaultProps} currentPage={5} totalPages={10} />);

      expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '10' })).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('handles zero total pages', () => {
      render(<Pagination {...defaultProps} currentPage={1} totalPages={0} />);

      // Should not render anything or render minimal UI
      expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    });

    it('accepts additional className prop', () => {
      const { container } = render(
        <Pagination {...defaultProps} className="custom-class" />
      );

      expect(container.querySelector('nav')).toHaveClass('custom-class');
    });
  });
});
