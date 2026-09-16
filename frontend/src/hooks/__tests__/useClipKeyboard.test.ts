import { act, renderHook } from '@testing-library/react';

import { SEEK_KEYS, useClipKeyboard } from '../useClipKeyboard';

function makeVideo(): HTMLVideoElement {
  const v = document.createElement('video');
  Object.defineProperty(v, 'duration', { value: 3600, configurable: true });
  v.pause = jest.fn();
  v.play = jest.fn().mockResolvedValue(undefined);
  Object.defineProperty(v, 'paused', { value: true, configurable: true });
  v.currentTime = 100;
  return v;
}

function press(key: string, extra: Partial<KeyboardEventInit> = {}) {
  const e = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...extra });
  const prevent = jest.spyOn(e, 'preventDefault');
  document.dispatchEvent(e);
  return prevent;
}

describe('useClipKeyboard', () => {
  it('캡처 단계에 등록한다 (네이티브 <video controls> 가 화살표를 먹지 못하게)', () => {
    const add = jest.spyOn(document, 'addEventListener');
    const videoRef = { current: makeVideo() };
    renderHook(() =>
      useClipKeyboard({ videoRef, enabled: true, onMarkStart: jest.fn(), onMarkEnd: jest.fn() })
    );
    const call = add.mock.calls.find((c) => c[0] === 'keydown');
    expect(call?.[2]).toBe(true);
    add.mockRestore();
  });

  it('화살표·PgUp/PgDn 은 고정 폭으로 이동하고 기본 동작을 막는다', () => {
    const video = makeVideo();
    const videoRef = { current: video };
    renderHook(() =>
      useClipKeyboard({ videoRef, enabled: true, onMarkStart: jest.fn(), onMarkEnd: jest.fn() })
    );
    expect(SEEK_KEYS.PageUp).toBe(-60);
    const prevent = press('ArrowRight');
    expect(video.currentTime).toBe(105);
    expect(prevent).toHaveBeenCalled();
    press('PageUp');
    expect(video.currentTime).toBe(45);
    press('ArrowUp');
    expect(video.currentTime).toBe(44);
  });

  it('입력창에 포커스가 있으면 무시하고 Esc 는 포커스를 뺀다', () => {
    const video = makeVideo();
    const videoRef = { current: video };
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    renderHook(() =>
      useClipKeyboard({ videoRef, enabled: true, onMarkStart: jest.fn(), onMarkEnd: jest.fn() })
    );
    press('ArrowRight');
    expect(video.currentTime).toBe(100);
    press('Escape');
    expect(document.activeElement).not.toBe(input);
    input.remove();
  });

  it('[ ] 는 시작/종료 지정, Space 는 재생 토글, 길게 누름은 180ms 스로틀', () => {
    const video = makeVideo();
    const videoRef = { current: video };
    const onMarkStart = jest.fn();
    const onMarkEnd = jest.fn();
    renderHook(() => useClipKeyboard({ videoRef, enabled: true, onMarkStart, onMarkEnd }));
    press('[');
    press(']');
    expect(onMarkStart).toHaveBeenCalledTimes(1);
    expect(onMarkEnd).toHaveBeenCalledTimes(1);
    press(' ');
    expect(video.play).toHaveBeenCalled();
    const now = jest.spyOn(performance, 'now');
    now.mockReturnValue(1000);
    press('ArrowRight');
    now.mockReturnValue(1050);
    press('ArrowRight', { repeat: true });
    expect(video.currentTime).toBe(105);
    now.mockReturnValue(1300);
    press('ArrowRight', { repeat: true });
    expect(video.currentTime).toBe(110);
    now.mockRestore();
  });

  it('enabled=false 면 아무것도 잡지 않는다', () => {
    const video = makeVideo();
    const videoRef = { current: video };
    renderHook(() =>
      useClipKeyboard({ videoRef, enabled: false, onMarkStart: jest.fn(), onMarkEnd: jest.fn() })
    );
    press('ArrowRight');
    expect(video.currentTime).toBe(100);
  });

  it('반환한 컨트롤은 상한을 넘지 않는다', () => {
    const video = makeVideo();
    const videoRef = { current: video };
    const { result } = renderHook(() =>
      useClipKeyboard({ videoRef, enabled: true, duration: 200, onMarkStart: jest.fn(), onMarkEnd: jest.fn() })
    );
    act(() => result.current.seekRel(500));
    expect(video.currentTime).toBe(200);
    act(() => result.current.frameStep(-1));
    expect(video.pause).toHaveBeenCalled();
  });
});
