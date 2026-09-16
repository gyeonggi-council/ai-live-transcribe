import { createRef } from 'react';

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Button } from '../ui';

describe('Button (ui primitive)', () => {
  describe('variants', () => {
    it('renders primary variant by default', () => {
      render(<Button>확인</Button>);

      const button = screen.getByRole('button', { name: '확인' });
      expect(button).toHaveClass('bg-primary');
      expect(button).toHaveClass('text-white');
      expect(button).toHaveClass('hover:bg-primary-dark');
    });

    it('renders secondary variant with light primary background', () => {
      render(<Button variant="secondary">보조</Button>);

      const button = screen.getByRole('button', { name: '보조' });
      expect(button).toHaveClass('bg-primary-5');
      expect(button).toHaveClass('text-primary-dark');
    });

    it('renders outline variant with gray border', () => {
      render(<Button variant="outline">외곽선</Button>);

      const button = screen.getByRole('button', { name: '외곽선' });
      expect(button).toHaveClass('border-gray-300');
      expect(button).toHaveClass('bg-white');
      expect(button).toHaveClass('text-gray-900');
    });

    it('renders danger variant with danger background', () => {
      render(<Button variant="danger">삭제</Button>);

      const button = screen.getByRole('button', { name: '삭제' });
      expect(button).toHaveClass('bg-danger');
      expect(button).toHaveClass('text-white');
      expect(button).toHaveClass('hover:bg-danger/90');
    });

    it('renders text variant without filled background', () => {
      render(<Button variant="text">텍스트</Button>);

      const button = screen.getByRole('button', { name: '텍스트' });
      expect(button).toHaveClass('hover:bg-gray-50');
      expect(button).not.toHaveClass('bg-primary');
    });
  });

  describe('sizes', () => {
    it('renders md size (40px) by default', () => {
      render(<Button>중간</Button>);

      const button = screen.getByRole('button', { name: '중간' });
      expect(button).toHaveClass('h-10');
      expect(button).toHaveClass('px-4');
    });

    it('renders sm size (32px)', () => {
      render(<Button size="sm">작게</Button>);

      const button = screen.getByRole('button', { name: '작게' });
      expect(button).toHaveClass('h-8');
      expect(button).toHaveClass('px-3');
      expect(button).toHaveClass('text-sm');
    });

    it('renders lg size (48px)', () => {
      render(<Button size="lg">크게</Button>);

      const button = screen.getByRole('button', { name: '크게' });
      expect(button).toHaveClass('h-12');
      expect(button).toHaveClass('px-5');
    });
  });

  describe('disabled', () => {
    it('is disabled and has opacity styling', () => {
      render(<Button disabled>비활성</Button>);

      const button = screen.getByRole('button', { name: '비활성' });
      expect(button).toBeDisabled();
      expect(button).toHaveClass('disabled:opacity-50');
    });

    it('does not call onClick when disabled', async () => {
      const onClick = jest.fn();
      const user = userEvent.setup();
      render(
        <Button disabled onClick={onClick}>
          비활성
        </Button>
      );

      await user.click(screen.getByRole('button', { name: '비활성' }));

      expect(onClick).not.toHaveBeenCalled();
    });
  });

  describe('loading', () => {
    it('shows spinner, sets aria-busy and disables the button', () => {
      const { container } = render(<Button loading>저장 중</Button>);

      const button = screen.getByRole('button', { name: '저장 중' });
      expect(button).toHaveAttribute('aria-busy', 'true');
      expect(button).toBeDisabled();
      expect(container.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('does not show spinner or aria-busy when not loading', () => {
      const { container } = render(<Button>저장</Button>);

      const button = screen.getByRole('button', { name: '저장' });
      expect(button).not.toHaveAttribute('aria-busy');
      expect(container.querySelector('.animate-spin')).not.toBeInTheDocument();
    });
  });

  describe('behavior', () => {
    it('calls onClick when clicked', async () => {
      const onClick = jest.fn();
      const user = userEvent.setup();
      render(<Button onClick={onClick}>클릭</Button>);

      await user.click(screen.getByRole('button', { name: '클릭' }));

      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it('defaults to type="button"', () => {
      render(<Button>기본</Button>);

      expect(screen.getByRole('button', { name: '기본' })).toHaveAttribute('type', 'button');
    });

    it('forwards ref to the underlying button element', () => {
      const ref = createRef<HTMLButtonElement>();
      render(<Button ref={ref}>참조</Button>);

      expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    });

    it('accepts additional className', () => {
      render(<Button className="custom-class">확장</Button>);

      expect(screen.getByRole('button', { name: '확장' })).toHaveClass('custom-class');
    });
  });
});
