import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SearchInput from '../SearchInput';

describe('SearchInput', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('rendering', () => {
    it('renders input field', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      expect(screen.getByRole('searchbox')).toBeInTheDocument();
    });

    it('shows placeholder text', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      expect(screen.getByPlaceholderText('키워드 검색...')).toBeInTheDocument();
    });

    it('shows search icon', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      expect(screen.getByTestId('search-icon')).toBeInTheDocument();
    });

    it('accepts custom placeholder', () => {
      render(<SearchInput onSearch={jest.fn()} placeholder="Search subtitles..." />);

      expect(screen.getByPlaceholderText('Search subtitles...')).toBeInTheDocument();
    });
  });

  describe('input handling', () => {
    it('updates value on input', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(<SearchInput onSearch={jest.fn()} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      expect(input).toHaveValue('test');
    });

    it('accepts initial value', () => {
      render(<SearchInput onSearch={jest.fn()} initialValue="initial" />);

      expect(screen.getByRole('searchbox')).toHaveValue('initial');
    });
  });

  describe('debounce', () => {
    it('calls onSearch after debounce delay', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const handleSearch = jest.fn();
      render(<SearchInput onSearch={handleSearch} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      // Should not be called immediately
      expect(handleSearch).not.toHaveBeenCalled();

      // Fast-forward time past debounce delay
      jest.advanceTimersByTime(300);

      expect(handleSearch).toHaveBeenCalledWith('test');
    });

    it('uses default debounce of 300ms', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const handleSearch = jest.fn();
      render(<SearchInput onSearch={handleSearch} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'a');

      // Not called at 200ms
      jest.advanceTimersByTime(200);
      expect(handleSearch).not.toHaveBeenCalled();

      // Called at 300ms
      jest.advanceTimersByTime(100);
      expect(handleSearch).toHaveBeenCalledWith('a');
    });

    it('accepts custom debounce delay', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const handleSearch = jest.fn();
      render(<SearchInput onSearch={handleSearch} debounceMs={500} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'a');

      // Not called at 400ms
      jest.advanceTimersByTime(400);
      expect(handleSearch).not.toHaveBeenCalled();

      // Called at 500ms
      jest.advanceTimersByTime(100);
      expect(handleSearch).toHaveBeenCalledWith('a');
    });

    it('only calls onSearch once for rapid typing', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const handleSearch = jest.fn();
      render(<SearchInput onSearch={handleSearch} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      // Fast-forward past debounce
      jest.advanceTimersByTime(300);

      expect(handleSearch).toHaveBeenCalledTimes(1);
      expect(handleSearch).toHaveBeenCalledWith('test');
    });
  });

  describe('clear button', () => {
    it('shows clear button when input has value', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(<SearchInput onSearch={jest.fn()} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      expect(screen.getByTestId('clear-button')).toBeInTheDocument();
    });

    it('hides clear button when input is empty', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      expect(screen.queryByTestId('clear-button')).not.toBeInTheDocument();
    });

    it('clears input when clear button is clicked', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(<SearchInput onSearch={jest.fn()} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      const clearButton = screen.getByTestId('clear-button');
      await user.click(clearButton);

      expect(input).toHaveValue('');
    });

    it('calls onSearch with empty string when cleared', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const handleSearch = jest.fn();
      render(<SearchInput onSearch={handleSearch} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');
      jest.advanceTimersByTime(300);
      handleSearch.mockClear();

      const clearButton = screen.getByTestId('clear-button');
      await user.click(clearButton);

      jest.advanceTimersByTime(300);

      expect(handleSearch).toHaveBeenCalledWith('');
    });

    it('calls onClear callback when cleared', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const handleClear = jest.fn();
      render(<SearchInput onSearch={jest.fn()} onClear={handleClear} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      const clearButton = screen.getByTestId('clear-button');
      await user.click(clearButton);

      expect(handleClear).toHaveBeenCalled();
    });
  });

  describe('styling', () => {
    it('has rounded border', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      const container = screen.getByTestId('search-input-container');
      expect(container).toHaveClass('rounded-lg');
    });

    it('has focus styles', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(<SearchInput onSearch={jest.fn()} />);

      const input = screen.getByRole('searchbox');
      await user.click(input);

      const container = screen.getByTestId('search-input-container');
      expect(container).toHaveClass('focus-within:border-primary');
    });

    it('has gray border by default', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      const container = screen.getByTestId('search-input-container');
      expect(container).toHaveClass('border-gray-300');
    });
  });

  describe('accessibility', () => {
    it('has search role', () => {
      render(<SearchInput onSearch={jest.fn()} />);

      expect(screen.getByRole('searchbox')).toBeInTheDocument();
    });

    it('clear button has accessible label', async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      render(<SearchInput onSearch={jest.fn()} />);

      const input = screen.getByRole('searchbox');
      await user.type(input, 'test');

      const clearButton = screen.getByTestId('clear-button');
      expect(clearButton).toHaveAttribute('aria-label', '검색어 지우기');
    });
  });
});
