import { render, screen } from '@testing-library/react';

import type { ClipSpeakerType } from '@/types';

import ClipSegmentPicker from '../ClipSegmentPicker';

const seg = (idx: number, start: number) => ({
  idx, start, end: start + 60, seconds: 60, time: '', title: `구간 ${idx + 1}`, named: true,
});

const SPEAKER: ClipSpeakerType = {
  key: 'k1', name: '김태희', role: '의원', party: null, district: null, photo_url: null,
  councilor_id: null, total_seconds: 240, segments: [seg(0, 100), seg(1, 400), seg(2, 900), seg(3, 1500)],
};

describe('ClipSegmentPicker', () => {
  it('줄마다 목록 순번(1부터)을 보인다 — 파일 이름 `이름_회의명_번호` 의 번호와 같은 값 (2026-09-10)', () => {
    render(
      <ClipSegmentPicker speaker={SPEAKER} checked={new Set([1, 3])} onToggle={jest.fn()} onPreview={jest.fn()} shift={0} />
    );
    const nos = screen.getAllByTestId('segment-no').map((el) => el.textContent);
    // 고른 것(2·4번)만이 아니라 전 줄에 순번이 붙는다 — 3번만 잘라도 파일이 _3 이라 줄과 짝지어진다
    expect(nos).toEqual(['1', '2', '3', '4']);
  });
});
