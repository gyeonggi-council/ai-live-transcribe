import { fireEvent, render, screen } from '@testing-library/react';

import type { ClipIndexType } from '@/types';

import SpeakerPicker from '../SpeakerPicker';

function makeIndex(source: ClipIndexType['source']): ClipIndexType {
  return {
    meeting_id: 'm1',
    kms_midx: '138270',
    duration: 3000,
    source,
    time_offset: 0,
    warnings: [],
    speakers: [
      {
        key: 'k1',
        name: '김지호',
        role: '위원',
        party: '더불어민주당',
        district: '부천시',
        photo_url: null,
        councilor_id: 'c1',
        total_seconds: 95,
        segments: [{ idx: 0, start: 1474, end: 1505, seconds: 31, time: '00:24:34', title: '자료요구(김지호 위원)', named: true }],
      },
    ],
  };
}

const base = {
  isLoading: false,
  error: null,
  selectedKey: null,
  onSelect: jest.fn(),
  shift: 0,
};

describe('SpeakerPicker', () => {
  it('서버가 자동으로 잘라 둔 의원은 카드에 「영상 준비됨」(2026-09-10)', () => {
    const { rerender } = render(<SpeakerPicker {...base} index={makeIndex('ai')} />);
    expect(screen.queryByTestId('auto-clip-ready')).toBeNull();
    rerender(<SpeakerPicker {...base} index={makeIndex('ai')} readyNames={new Set(['김지호'])} />);
    expect(screen.getByTestId('auto-clip-ready')).toHaveTextContent('영상 준비됨');
  });

  it.each([
    ['official', '공식 인덱스'],
    ['ai', 'AI 자막(잠정)'],
    ['live', '실시간 자막(초안)'],
  ] as const)('source=%s → 배지 %s', (source, label) => {
    render(<SpeakerPicker {...base} index={makeIndex(source)} />);
    expect(screen.getByTestId('source-badge')).toHaveTextContent(label);
  });

  it('ai 는 잠정 경고(질의~답변 한 구간)가 뜨고 official 은 없다 — 시간 맞추기 상자는 어디에도 없다(2026-09-08 폐기)', () => {
    const { rerender } = render(<SpeakerPicker {...base} index={makeIndex('ai')} />);
    expect(screen.getByTestId('provisional-warning')).toHaveTextContent('집행부 답변까지');
    // 2026-09-10 파일 이름이 `이름_회의명_번호` 가 되며 _AI잠정 이 빠졌다 — 안내도 그 말을 하지 않는다
    expect(screen.getByTestId('provisional-warning')).not.toHaveTextContent('_AI잠정');
    expect(screen.queryByTestId('clip-offset-control')).not.toBeInTheDocument();
    rerender(<SpeakerPicker {...base} index={makeIndex('official')} />);
    expect(screen.queryByTestId('provisional-warning')).not.toBeInTheDocument();
    expect(screen.queryByTestId('clip-offset-control')).not.toBeInTheDocument();
  });

  it('의원 카드에 정당·선거구·구간 수·첫 발언 시각이 있고 클릭하면 onSelect', () => {
    const onSelect = jest.fn();
    render(<SpeakerPicker {...base} index={makeIndex('ai')} onSelect={onSelect} />);
    const card = screen.getByTestId('speaker-card');
    expect(card).toHaveTextContent('김지호');
    expect(card).toHaveTextContent('더불어민주당 · 부천시');
    expect(card).toHaveTextContent('1개 구간');
    expect(card).toHaveTextContent('첫 발언 00:24:34');
    fireEvent.click(card);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ name: '김지호' }));
  });

  it('의원이 없으면 수동 자르기 안내', () => {
    const idx = { ...makeIndex('none'), speakers: [], warnings: ['자막이 없어 발언 구간을 추정할 수 없습니다.'] };
    render(<SpeakerPicker {...base} index={idx} />);
    expect(screen.getByTestId('speaker-empty')).toHaveTextContent('자막이 없어');
    expect(screen.getByTestId('speaker-empty')).toHaveTextContent('직접 구간을 지정');
  });
});
