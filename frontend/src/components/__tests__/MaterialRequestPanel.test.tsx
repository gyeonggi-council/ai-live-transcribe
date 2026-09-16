import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import type { MaterialRequestType } from '@/types';

import MaterialRequestPanel from '../MaterialRequestPanel';

const makeRequest = (
  overrides: Partial<MaterialRequestType> = {}
): MaterialRequestType => ({
  id: 'r1',
  meeting_id: 'm1',
  subtitle_id: 's1',
  start_time: 1493, // 24:53
  speaker: '화자 4',
  councilor_name: '이혜원',
  summary: '지방채 발행 검토 자료',
  request_text: '그 자료 제출해 주시고요.',
  department: null,
  confidence: 'high',
  status: 'detected',
  source: 'live',
  ...overrides,
});

describe('MaterialRequestPanel', () => {
  it('감지 항목과 미확인 배지를 표시한다', () => {
    render(
      <MaterialRequestPanel
        requests={[makeRequest()]}
        onUpdate={jest.fn()}
      />
    );
    expect(screen.getByTestId('material-request-panel')).toBeInTheDocument();
    expect(screen.getByText('지방채 발행 검토 자료')).toBeInTheDocument();
    expect(screen.getByText('이혜원')).toBeInTheDocument();
    expect(screen.getByTestId('material-request-pending-badge')).toHaveTextContent(
      '미확인 1'
    );
    expect(screen.getByText('24:53')).toBeInTheDocument();
  });

  it('빈 목록이면 안내 문구를 표시한다', () => {
    render(<MaterialRequestPanel requests={[]} onUpdate={jest.fn()} />);
    expect(screen.getByTestId('material-request-empty')).toBeInTheDocument();
  });

  it('확인 버튼이 status confirmed 업데이트를 호출한다', () => {
    const onUpdate = jest.fn();
    render(<MaterialRequestPanel requests={[makeRequest()]} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByTestId('material-request-confirm'));
    expect(onUpdate).toHaveBeenCalledWith('r1', { status: 'confirmed' });
  });

  it('무시 버튼이 status dismissed 업데이트를 호출한다', () => {
    const onUpdate = jest.fn();
    render(<MaterialRequestPanel requests={[makeRequest()]} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByTestId('material-request-dismiss'));
    expect(onUpdate).toHaveBeenCalledWith('r1', { status: 'dismissed' });
  });

  it('확인됨 상태에서는 등록 완료 버튼이 보인다', () => {
    const onUpdate = jest.fn();
    render(
      <MaterialRequestPanel
        requests={[makeRequest({ status: 'confirmed' })]}
        onUpdate={onUpdate}
      />
    );
    fireEvent.click(screen.getByTestId('material-request-mark-registered'));
    expect(onUpdate).toHaveBeenCalledWith('r1', { status: 'registered' });
  });

  it('무시된 항목은 기본 숨김, 토글로 표시한다', () => {
    render(
      <MaterialRequestPanel
        requests={[makeRequest({ id: 'r2', status: 'dismissed', summary: '무시된 자료' })]}
        onUpdate={jest.fn()}
      />
    );
    expect(screen.queryByText('무시된 자료')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('material-request-toggle-dismissed'));
    expect(screen.getByText('무시된 자료')).toBeInTheDocument();
  });

  it('복사 버튼이 KMS 등록용 제목을 클립보드에 복사한다', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MaterialRequestPanel requests={[makeRequest()]} onUpdate={jest.fn()} />);
    fireEvent.click(screen.getByTestId('material-request-copy'));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith('이혜원 의원 요구자료(지방채 발행 검토 자료)')
    );
  });

  it('onScan이 있으면 AI 스캔 버튼을 노출하고 클릭 시 호출한다', async () => {
    const onScan = jest.fn().mockResolvedValue(3);
    render(
      <MaterialRequestPanel requests={[]} onUpdate={jest.fn()} onScan={onScan} />
    );
    fireEvent.click(screen.getByTestId('material-request-scan-button'));
    await waitFor(() => expect(onScan).toHaveBeenCalled());
  });

  it('onScan이 없으면(라이브 모드) 스캔 버튼을 숨긴다', () => {
    render(<MaterialRequestPanel requests={[]} onUpdate={jest.fn()} />);
    expect(screen.queryByTestId('material-request-scan-button')).not.toBeInTheDocument();
  });

  it('수동 추가 폼으로 항목을 추가한다', async () => {
    const onAddManual = jest.fn().mockResolvedValue(undefined);
    render(
      <MaterialRequestPanel requests={[]} onUpdate={jest.fn()} onAddManual={onAddManual} />
    );
    fireEvent.click(screen.getByTestId('material-request-add-toggle'));
    fireEvent.change(screen.getByTestId('material-request-manual-councilor'), {
      target: { value: '오창준' },
    });
    fireEvent.change(screen.getByTestId('material-request-manual-summary'), {
      target: { value: '미수납액 현황' },
    });
    fireEvent.click(screen.getByTestId('material-request-manual-submit'));
    await waitFor(() =>
      expect(onAddManual).toHaveBeenCalledWith({
        summary: '미수납액 현황',
        councilor_name: '오창준',
      })
    );
  });

  it('onJumpTo가 있으면 시각 클릭 시 초와 subtitle_id를 함께 전달한다', () => {
    const onJumpTo = jest.fn();
    render(
      <MaterialRequestPanel
        requests={[makeRequest()]}
        onUpdate={jest.fn()}
        onJumpTo={onJumpTo}
      />
    );
    fireEvent.click(screen.getByText('24:53'));
    // subtitle_id는 자막 패널 스크롤 연동용 — 영상 시크와 함께 전달된다
    expect(onJumpTo).toHaveBeenCalledWith(1493, 's1');
  });

  it('fullViewHref가 있으면 새 창 전체 화면 링크를 노출한다', () => {
    render(
      <MaterialRequestPanel
        requests={[makeRequest()]}
        onUpdate={jest.fn()}
        fullViewHref="/vod/m1/materials"
      />
    );
    const link = screen.getByTestId('material-request-full-view');
    expect(link).toHaveAttribute('href', '/vod/m1/materials');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('fullHeight 모드는 인용문을 줄임 없이 전체 표시한다', () => {
    render(
      <MaterialRequestPanel
        requests={[makeRequest()]}
        onUpdate={jest.fn()}
        fullHeight
      />
    );
    const quote = screen.getByText(/그 자료 제출해 주시고요/);
    expect(quote.className).not.toContain('line-clamp');
  });

  it('기본(임베드) 모드는 인용문을 line-clamp로 줄여 표시한다', () => {
    render(<MaterialRequestPanel requests={[makeRequest()]} onUpdate={jest.fn()} />);
    const quote = screen.getByText(/그 자료 제출해 주시고요/);
    expect(quote.className).toContain('line-clamp-4');
  });
});
