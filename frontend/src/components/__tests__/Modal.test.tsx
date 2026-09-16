import { useState } from 'react';

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Modal } from '../ui';

describe('Modal (ui primitive)', () => {
  const onClose = jest.fn();

  beforeEach(() => {
    onClose.mockClear();
  });

  it('renders nothing when closed', () => {
    render(
      <Modal isOpen={false} onClose={onClose} title="테스트 모달">
        내용
      </Modal>
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders dialog with aria-modal and aria-labelledby pointing to the title', () => {
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달">
        내용
      </Modal>
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const titleEl = document.getElementById(labelledBy as string);
    expect(titleEl).toHaveTextContent('테스트 모달');
  });

  it('calls onClose when Escape is pressed', async () => {
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달">
        내용
      </Modal>
    );

    await user.keyboard('{Escape}');

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not close on Escape when closeDisabled', async () => {
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달" closeDisabled>
        내용
      </Modal>
    );

    await user.keyboard('{Escape}');

    expect(onClose).not.toHaveBeenCalled();
  });

  it('calls onClose when the close (X) button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달">
        내용
      </Modal>
    );

    await user.click(screen.getByRole('button', { name: '닫기' }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when the overlay is clicked', async () => {
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달">
        내용
      </Modal>
    );

    await user.click(screen.getByTestId('modal-overlay'));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not close on overlay click and disables the X button when closeDisabled', async () => {
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달" closeDisabled>
        내용
      </Modal>
    );

    await user.click(screen.getByTestId('modal-overlay'));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '닫기' })).toBeDisabled();
  });

  it('does not call onClose when clicking inside the dialog', async () => {
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달">
        <p>본문 내용</p>
      </Modal>
    );

    await user.click(screen.getByText('본문 내용'));

    expect(onClose).not.toHaveBeenCalled();
  });

  describe('focus trap', () => {
    it('moves focus to the first focusable element on open', () => {
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달">
          <button>첫 버튼</button>
        </Modal>
      );

      // 헤더의 닫기(X) 버튼이 DOM상 첫 포커서블 요소
      expect(screen.getByRole('button', { name: '닫기' })).toHaveFocus();
    });

    it('cycles focus back to the first element when tabbing past the last', async () => {
      const user = userEvent.setup();
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달">
          <button>버튼 1</button>
          <button>버튼 2</button>
        </Modal>
      );

      // 초점: 닫기 → 버튼1 → 버튼2 → (순환) 닫기
      await user.tab();
      expect(screen.getByRole('button', { name: '버튼 1' })).toHaveFocus();
      await user.tab();
      expect(screen.getByRole('button', { name: '버튼 2' })).toHaveFocus();
      await user.tab();
      expect(screen.getByRole('button', { name: '닫기' })).toHaveFocus();
    });

    it('cycles focus to the last element when shift-tabbing from the first', async () => {
      const user = userEvent.setup();
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달">
          <button>버튼 1</button>
        </Modal>
      );

      expect(screen.getByRole('button', { name: '닫기' })).toHaveFocus();
      await user.tab({ shift: true });
      expect(screen.getByRole('button', { name: '버튼 1' })).toHaveFocus();
    });

    it('restores focus to the trigger element when the modal closes', async () => {
      const user = userEvent.setup();

      function TriggerConsumer() {
        const [open, setOpen] = useState(false);

        return (
          <>
            <button onClick={() => setOpen(true)}>모달 열기</button>
            <Modal isOpen={open} onClose={() => setOpen(false)} title="테스트 모달">
              내용
            </Modal>
          </>
        );
      }

      render(<TriggerConsumer />);

      const trigger = screen.getByRole('button', { name: '모달 열기' });
      await user.click(trigger);
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      await user.keyboard('{Escape}');

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it('keeps focus in a controlled input across re-renders with an inline onClose', async () => {
      // 회귀: 소비자가 인라인 onClose를 넘기고 제어형 입력으로 리렌더될 때
      // 초점 트랩 effect가 재실행되어 타이핑 초점을 강탈하면 안 됨 (VodRegisterModal 이식 케이스)
      const user = userEvent.setup();

      function ControlledConsumer() {
        const [open, setOpen] = useState(true);
        const [value, setValue] = useState('');

        if (!open) {
          return null;
        }

        return (
          <Modal isOpen={open} onClose={() => setOpen(false)} title="폼 모달">
            <input
              aria-label="제목 입력"
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </Modal>
        );
      }

      render(<ControlledConsumer />);

      const input = screen.getByLabelText('제목 입력');
      await user.click(input);
      await user.keyboard('경기도의회');

      expect(input).toHaveFocus();
      expect(input).toHaveValue('경기도의회');
    });
  });

  describe('sizes', () => {
    it('renders md size (max-w-lg) by default', () => {
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달">
          내용
        </Modal>
      );

      expect(screen.getByRole('dialog')).toHaveClass('max-w-lg');
    });

    it('renders sm size', () => {
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달" size="sm">
          내용
        </Modal>
      );

      expect(screen.getByRole('dialog')).toHaveClass('max-w-sm');
    });

    it('renders lg size', () => {
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달" size="lg">
          내용
        </Modal>
      );

      expect(screen.getByRole('dialog')).toHaveClass('max-w-2xl');
    });

    it('renders full size with near-fullscreen classes', () => {
      render(
        <Modal isOpen onClose={onClose} title="테스트 모달" size="full">
          내용
        </Modal>
      );

      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveClass('max-w-[95vw]');
      expect(dialog).toHaveClass('h-[90vh]');
    });
  });

  it('renders footer slot when provided', () => {
    render(
      <Modal isOpen onClose={onClose} title="테스트 모달" footer={<button>저장</button>}>
        내용
      </Modal>
    );

    expect(screen.getByRole('button', { name: '저장' })).toBeInTheDocument();
  });
});
