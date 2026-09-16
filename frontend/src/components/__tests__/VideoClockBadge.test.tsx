/**
 * 영상 위 실제 시각 배지.
 *
 * 지키려는 것: ① 값이 아니라 **함수**를 주기적으로 읽어 렌더가 드물어도 초가 흐른다,
 * ② 근거(기준점)가 없으면 **아무것도 그리지 않는다** — 틀린 시각보다 없는 편이 낫다.
 */

import React from 'react';

import { act, render, screen } from '@testing-library/react';

import VideoClockBadge from '../VideoClockBadge';

const at = (h: number, m: number, s = 0) => new Date(2026, 8, 16, h, m, s).getTime();

describe('VideoClockBadge', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('장면의 실제 시각을 시:분:초로 보여준다', () => {
    render(<VideoClockBadge getWallMs={() => at(12, 7, 23)} />);
    expect(screen.getByTestId('video-clock')).toHaveTextContent('12:07:23');
  });

  it('렌더가 없어도 스스로 갱신한다 (라이브 영상은 계속 흐른다)', () => {
    let now = at(12, 7, 23);
    render(<VideoClockBadge getWallMs={() => now} />);
    expect(screen.getByTestId('video-clock')).toHaveTextContent('12:07:23');

    now = at(12, 7, 25);
    act(() => {
      jest.advanceTimersByTime(600);
    });
    expect(screen.getByTestId('video-clock')).toHaveTextContent('12:07:25');
  });

  it('근거가 없으면 그리지 않는다', () => {
    render(<VideoClockBadge getWallMs={() => null} />);
    expect(screen.queryByTestId('video-clock')).not.toBeInTheDocument();
  });

  it('추정 기준점이면 "약"을 붙여 근사임을 드러낸다', () => {
    render(<VideoClockBadge getWallMs={() => at(12, 7, 23)} approximate />);
    expect(screen.getByTestId('video-clock')).toHaveTextContent('약 12:07:23');
  });

  it('VOD 는 날짜까지 보여준다 (지난 회의라 오늘이 아니다)', () => {
    render(<VideoClockBadge getWallMs={() => at(12, 7, 23)} withDate />);
    expect(screen.getByTestId('video-clock')).toHaveTextContent('2026-09-16 12:07:23');
  });
});
