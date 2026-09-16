import { fireEvent, render, screen } from '@testing-library/react';

import ClipControlRail from '../ClipControlRail';

function setup(over: Partial<React.ComponentProps<typeof ClipControlRail>> = {}) {
  const props = {
    currentTime: 754,
    duration: 3600,
    isPaused: true,
    selStart: 100,
    selEnd: 256,
    onSeekRel: jest.fn(),
    onSeekTo: jest.fn(),
    onFrameStep: jest.fn(),
    onTogglePlay: jest.fn(),
    onMarkStart: jest.fn(),
    onMarkEnd: jest.fn(),
    onEditStart: jest.fn(),
    onEditEnd: jest.fn(),
    onPlaySelection: jest.fn(),
    onExtractSelection: jest.fn(),
    ...over,
  };
  render(<ClipControlRail {...props} />);
  return props;
}

describe('ClipControlRail', () => {
  it('단축키가 버튼 라벨에 있고, 별도 안내 줄은 없다', () => {
    setup();
    const rail = screen.getByTestId('clip-control-rail');
    expect(rail).toHaveTextContent('-5초');
    expect(rail).toHaveTextContent('←');
    expect(rail).toHaveTextContent('PgUp');
    expect(rail).toHaveTextContent('Space');
    expect(rail).toHaveTextContent('[');
    expect(rail).toHaveTextContent(']');
    // 옛 데스크톱 안내 줄("Space 재생/정지 · ← → 5초 …")은 없다
    expect(screen.queryByText(/재생\/정지 ·/)).not.toBeInTheDocument();
    expect(screen.queryByText(/시간 마킹/)).not.toBeInTheDocument();
  });

  it('이동 버튼은 고정 폭으로 콜백한다', () => {
    const p = setup();
    fireEvent.click(screen.getByTitle('5초 뒤로'));
    fireEvent.click(screen.getByTitle('1분 앞으로'));
    fireEvent.click(screen.getByTitle('한 프레임 앞으로'));
    expect(p.onSeekRel).toHaveBeenCalledWith(-5);
    expect(p.onSeekRel).toHaveBeenCalledWith(60);
    expect(p.onFrameStep).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByTestId('btn-play'));
    expect(p.onTogglePlay).toHaveBeenCalled();
  });

  it('시각 입력 + Enter 로 바로 이동한다 (12:30 → 750초)', () => {
    const p = setup();
    const input = screen.getByTestId('jump-input');
    fireEvent.change(input, { target: { value: '12:30' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(p.onSeekTo).toHaveBeenCalledWith(750);
    expect((input as HTMLInputElement).value).toBe('');
  });

  it('시작·종료 마킹 버튼과 구간 길이', () => {
    const p = setup();
    expect(screen.getByTestId('sel-length')).toHaveTextContent('2분 36초');
    expect(screen.getByTestId('sel-start')).toHaveValue('00:01:40');
    fireEvent.click(screen.getByTestId('btn-mark-start'));
    fireEvent.click(screen.getByTestId('btn-mark-end'));
    expect(p.onMarkStart).toHaveBeenCalled();
    expect(p.onMarkEnd).toHaveBeenCalled();
  });

  it('시각 칸을 직접 고치면 onEditStart/onEditEnd', () => {
    const p = setup();
    const s = screen.getByTestId('sel-start');
    fireEvent.change(s, { target: { value: '00:02:00' } });
    fireEvent.blur(s);
    expect(p.onEditStart).toHaveBeenCalledWith(120);
    const e = screen.getByTestId('sel-end');
    fireEvent.change(e, { target: { value: 'abc' } });
    fireEvent.blur(e);
    expect(p.onEditEnd).not.toHaveBeenCalled();
    expect(e).toHaveValue('00:04:16');
  });

  it('이 구간 추출', () => {
    const p = setup();
    fireEvent.click(screen.getByTestId('btn-extract-selection'));
    expect(p.onExtractSelection).toHaveBeenCalled();
  });
});
