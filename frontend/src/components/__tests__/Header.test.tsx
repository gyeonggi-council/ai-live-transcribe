import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import Header from '../Header';

describe('Header', () => {
  describe('logo', () => {
    it('renders logo with text "경기도의회 자막"', () => {
      render(<Header />);

      const logo = screen.getByText('경기도의회 자막');
      expect(logo).toBeInTheDocument();
      expect(logo.closest('a')).toHaveAttribute('href', '/');
    });
  });

  describe('title', () => {
    it('renders title when provided', () => {
      render(<Header title="Test Meeting Title" />);

      expect(screen.getByText('Test Meeting Title')).toBeInTheDocument();
    });

    it('does not render title when not provided', () => {
      render(<Header />);

      // Only logo should be present, no additional title
      const title = screen.queryByRole('heading');
      expect(title).not.toBeInTheDocument();
    });
  });

  describe('badges', () => {
    it('shows Live badge when showLiveBadge is true', () => {
      render(<Header showLiveBadge />);

      expect(screen.getByText('Live')).toBeInTheDocument();
    });

    it('shows VOD badge when showVodBadge is true', () => {
      render(<Header showVodBadge />);

      expect(screen.getByText('VOD')).toBeInTheDocument();
    });

    it('does not show badges by default', () => {
      render(<Header />);

      expect(screen.queryByText('Live')).not.toBeInTheDocument();
      expect(screen.queryByText('VOD')).not.toBeInTheDocument();
    });
  });

  describe('search slot', () => {
    it('renders search slot content when showSearch is true', () => {
      render(
        <Header showSearch>
          <input placeholder="Search..." data-testid="search-input" />
        </Header>
      );

      expect(screen.getByTestId('search-input')).toBeInTheDocument();
    });

    it('does not render children when showSearch is false', () => {
      render(
        <Header showSearch={false}>
          <input placeholder="Search..." data-testid="search-input" />
        </Header>
      );

      expect(screen.queryByTestId('search-input')).not.toBeInTheDocument();
    });
  });

  describe('VOD register button', () => {
    it('shows register button when showRegisterButton is true', () => {
      render(<Header showRegisterButton />);

      expect(screen.getByRole('button', { name: 'VOD 등록' })).toBeInTheDocument();
    });

    it('calls onRegisterClick when register button is clicked', async () => {
      const user = userEvent.setup();
      const handleRegisterClick = jest.fn();

      render(<Header showRegisterButton onRegisterClick={handleRegisterClick} />);

      await user.click(screen.getByRole('button', { name: 'VOD 등록' }));

      expect(handleRegisterClick).toHaveBeenCalledTimes(1);
    });

    it('does not show register button by default', () => {
      render(<Header />);

      expect(screen.queryByRole('button', { name: 'VOD 등록' })).not.toBeInTheDocument();
    });
  });

  describe('styling', () => {
    it('has correct header styling', () => {
      render(<Header />);

      const header = screen.getByRole('banner');
      expect(header).toHaveClass('h-16');
      expect(header).toHaveClass('bg-white');
      expect(header).toHaveClass('border-b');
    });
  });
});
