import { render, screen } from '@testing-library/react';

import { Input, Select, Textarea } from '../ui';

describe('Input (ui primitive)', () => {
  it('renders label linked to the input', () => {
    render(<Input label="제목" />);

    const input = screen.getByLabelText('제목');
    expect(input).toBeInTheDocument();
    expect(input.tagName).toBe('INPUT');
  });

  it('applies KRDS default border styles', () => {
    render(<Input label="제목" />);

    const input = screen.getByLabelText('제목');
    expect(input).toHaveClass('border-gray-300');
    expect(input).toHaveClass('focus:border-primary');
  });

  it('shows error with aria-invalid and aria-describedby', () => {
    render(<Input label="제목" error="필수 입력입니다." />);

    const input = screen.getByLabelText('제목');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveClass('border-error');

    const errorEl = screen.getByText('필수 입력입니다.');
    expect(errorEl).toHaveClass('text-error');
    expect(input.getAttribute('aria-describedby')).toContain(errorEl.id);
  });

  it('does not set aria-invalid without error', () => {
    render(<Input label="제목" />);

    expect(screen.getByLabelText('제목')).not.toHaveAttribute('aria-invalid');
  });

  it('shows help text linked via aria-describedby', () => {
    render(<Input label="제목" help="회의 제목을 입력하세요." />);

    const input = screen.getByLabelText('제목');
    const helpEl = screen.getByText('회의 제목을 입력하세요.');
    expect(input.getAttribute('aria-describedby')).toContain(helpEl.id);
  });
});

describe('Select (ui primitive)', () => {
  it('renders label linked to the select with options', () => {
    render(
      <Select label="분류">
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>
    );

    const select = screen.getByLabelText('분류');
    expect(select.tagName).toBe('SELECT');
    expect(screen.getByRole('option', { name: 'A' })).toBeInTheDocument();
  });

  it('shows error with aria-invalid and aria-describedby', () => {
    render(
      <Select label="분류" error="선택해주세요.">
        <option value="a">A</option>
      </Select>
    );

    const select = screen.getByLabelText('분류');
    expect(select).toHaveAttribute('aria-invalid', 'true');
    expect(select).toHaveClass('border-error');

    const errorEl = screen.getByText('선택해주세요.');
    expect(select.getAttribute('aria-describedby')).toContain(errorEl.id);
  });

  it('shows help text linked via aria-describedby', () => {
    render(
      <Select label="분류" help="회의 분류를 선택하세요.">
        <option value="a">A</option>
      </Select>
    );

    const select = screen.getByLabelText('분류');
    const helpEl = screen.getByText('회의 분류를 선택하세요.');
    expect(select.getAttribute('aria-describedby')).toContain(helpEl.id);
  });
});

describe('Textarea (ui primitive)', () => {
  it('renders label linked to the textarea', () => {
    render(<Textarea label="내용" />);

    const textarea = screen.getByLabelText('내용');
    expect(textarea.tagName).toBe('TEXTAREA');
    expect(textarea).toHaveClass('border-gray-300');
  });

  it('shows error with aria-invalid and aria-describedby', () => {
    render(<Textarea label="내용" error="내용을 입력해주세요." />);

    const textarea = screen.getByLabelText('내용');
    expect(textarea).toHaveAttribute('aria-invalid', 'true');
    expect(textarea).toHaveClass('border-error');

    const errorEl = screen.getByText('내용을 입력해주세요.');
    expect(textarea.getAttribute('aria-describedby')).toContain(errorEl.id);
  });

  it('shows help text linked via aria-describedby', () => {
    render(<Textarea label="내용" help="상세 내용을 적어주세요." />);

    const textarea = screen.getByLabelText('내용');
    const helpEl = screen.getByText('상세 내용을 적어주세요.');
    expect(textarea.getAttribute('aria-describedby')).toContain(helpEl.id);
  });
});
