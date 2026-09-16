import { fireEvent, render, screen } from '@testing-library/react';

import ClipTimeline from '../ClipTimeline';

// jsdom 에는 PointerEvent 가 없다 — fireEvent.pointerMove 가 clientX 를 실어 나르게 MouseEvent 로 대신한다
beforeAll(() => {
  if (typeof window.PointerEvent === 'undefined') {
    class PointerEventShim extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    (window as unknown as { PointerEvent: typeof PointerEventShim }).PointerEvent = PointerEventShim;
  }
  HTMLElement.prototype.setPointerCapture = HTMLElement.prototype.setPointerCapture || (() => undefined);
});

function mockRect(el: HTMLElement, width = 1000) {
  el.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width, height: 36, right: width, bottom: 36, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
}

describe('ClipTimeline', () => {
  const base = {
    duration: 2000,
    currentTime: 500,
    selStart: 400,
    selEnd: 1000,
    marks: [
      { start: 100, end: 200, active: true },
      { start: 1500, end: 1600 },
    ],
  };

  it('막대 클릭 = 그 비율의 시각으로 시크', () => {
    const onSeek = jest.fn();
    render(<ClipTimeline {...base} onSeek={onSeek} onChangeSelection={jest.fn()} />);
    const bar = screen.getByTestId('clip-timeline-bar');
    mockRect(bar);
    fireEvent.click(bar, { clientX: 500 });
    expect(onSeek).toHaveBeenCalledWith(1000);
  });

  it('발언 구간 눈금과 선택 구간·현재 위치를 그린다', () => {
    render(<ClipTimeline {...base} onSeek={jest.fn()} onChangeSelection={jest.fn()} />);
    expect(screen.getAllByTestId('clip-timeline-mark')).toHaveLength(2);
    expect(screen.getByTestId('clip-timeline-selection')).toHaveStyle({ left: '20%', width: '30%' });
    expect(screen.getByTestId('clip-timeline-cursor')).toHaveStyle({ left: '25%' });
    expect(screen.getByTestId('clip-timeline-current')).toHaveTextContent('00:08:20');
  });

  it('시작 핸들 드래그는 종료를 넘지 못하고, 막대 시킹을 일으키지 않는다', () => {
    const onSeek = jest.fn();
    const onChange = jest.fn();
    render(<ClipTimeline {...base} onSeek={onSeek} onChangeSelection={onChange} />);
    mockRect(screen.getByTestId('clip-timeline-bar'));
    const handle = screen.getByTestId('clip-handle-start');
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 200 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 750 });
    expect(onChange).toHaveBeenLastCalledWith({ start: 1000, end: 1000 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100 });
    expect(onChange).toHaveBeenLastCalledWith({ start: 200, end: 1000 });
    fireEvent.pointerUp(handle, { pointerId: 1 });
    fireEvent.click(handle);
    expect(onSeek).not.toHaveBeenCalled();
  });

  it('종료 핸들 드래그는 시작 아래로 내려가지 않는다', () => {
    const onChange = jest.fn();
    render(<ClipTimeline {...base} onSeek={jest.fn()} onChangeSelection={onChange} />);
    mockRect(screen.getByTestId('clip-timeline-bar'));
    const handle = screen.getByTestId('clip-handle-end');
    fireEvent.pointerDown(handle, { pointerId: 2, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 50 });
    expect(onChange).toHaveBeenLastCalledWith({ start: 400, end: 400 });
  });

  it('길이가 0 이면 핸들·선택을 그리지 않는다', () => {
    render(<ClipTimeline {...base} duration={0} selStart={0} selEnd={0} onSeek={jest.fn()} onChangeSelection={jest.fn()} />);
    expect(screen.queryByTestId('clip-handle-start')).not.toBeInTheDocument();
    expect(screen.queryByTestId('clip-timeline-selection')).not.toBeInTheDocument();
  });
});
