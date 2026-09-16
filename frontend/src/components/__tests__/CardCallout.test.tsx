import { render, screen } from '@testing-library/react';

import { Card, Callout } from '../ui';

describe('Card (ui primitive)', () => {
  it('renders children with KRDS card styles', () => {
    render(<Card data-testid="card">카드 내용</Card>);

    const card = screen.getByTestId('card');
    expect(card).toHaveTextContent('카드 내용');
    expect(card).toHaveClass('bg-white');
    expect(card).toHaveClass('border-border');
    expect(card).toHaveClass('rounded-lg');
    expect(card).toHaveClass('p-4'); // md 기본
  });

  it('supports padding variants', () => {
    render(
      <>
        <Card data-testid="card-none" padding="none">
          A
        </Card>
        <Card data-testid="card-lg" padding="lg">
          B
        </Card>
      </>
    );

    expect(screen.getByTestId('card-none')).not.toHaveClass('p-4');
    expect(screen.getByTestId('card-lg')).toHaveClass('p-6');
  });

  it('accepts additional className', () => {
    render(
      <Card data-testid="card" className="custom-class">
        C
      </Card>
    );

    expect(screen.getByTestId('card')).toHaveClass('custom-class');
  });
});

describe('Callout (ui primitive)', () => {
  it('renders info variant by default with icon', () => {
    const { container } = render(<Callout>안내 문구</Callout>);

    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('안내 문구');
    expect(note).toHaveClass('bg-info/5');
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('renders success variant', () => {
    render(<Callout variant="success">완료되었습니다</Callout>);

    expect(screen.getByRole('note')).toHaveClass('bg-success/5');
  });

  it('renders warning variant', () => {
    render(<Callout variant="warning">주의하세요</Callout>);

    expect(screen.getByRole('note')).toHaveClass('bg-warning-bg/10');
  });

  it('renders danger variant with role="alert"', () => {
    render(<Callout variant="danger">위험 안내</Callout>);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('위험 안내');
    expect(alert).toHaveClass('bg-danger/5');
  });

  it('renders optional title', () => {
    render(
      <Callout variant="info" title="알림">
        본문
      </Callout>
    );

    expect(screen.getByText('알림')).toHaveClass('font-semibold');
  });
});
