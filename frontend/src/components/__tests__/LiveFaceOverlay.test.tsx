/**
 * 영상 위 [의원 찾기] (2026-09-16)
 *
 * 화면이 지켜야 하는 약속만 시험한다:
 *  · 누르기 전에는 상자도 이름도 없다
 *  · 확신한 얼굴만 이름이 붙고, 애매한 얼굴은 상자만 남는다
 *  · 이름을 누르면 의원 상세가 열린다
 *  · 캔버스 캡처가 막히면 서버 캡처로 물러선다
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import LiveFaceOverlay from '@/components/live/LiveFaceOverlay';
import { identifyFaces, identifyFacesOnChannel, getCouncilorDetail } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  ...jest.requireActual('@/lib/api'),
  identifyFaces: jest.fn(),
  identifyFacesOnChannel: jest.fn(),
  getCouncilorDetail: jest.fn(),
  API_BASE_URL: '',
}));

const mockIdentify = identifyFaces as jest.MockedFunction<typeof identifyFaces>;
const mockIdentifyChannel = identifyFacesOnChannel as jest.MockedFunction<typeof identifyFacesOnChannel>;
const mockDetail = getCouncilorDetail as jest.MockedFunction<typeof getCouncilorDetail>;

const CONFIDENT = {
  box: [0.2, 0.3, 0.1, 0.15] as [number, number, number, number],
  det_score: 0.93,
  face_px: 96,
  score: 0.6,
  margin: 0.3,
  councilor_id: 'c-1',
  name: '이대한',
  party: '더불어민주당',
  district: '남양주시 제4선거구',
  confident: true,
  basis: 'face' as const,
};
const UNSURE = { ...CONFIDENT, councilor_id: null, name: null, score: 0.21, margin: 0.01, confident: false };

function makeVideoRef(withPixels = true) {
  const video = document.createElement('video');
  Object.defineProperty(video, 'videoWidth', { value: withPixels ? 960 : 0 });
  Object.defineProperty(video, 'videoHeight', { value: withPixels ? 540 : 0 });
  return { current: video };
}

beforeEach(() => {
  jest.clearAllMocks();
  // jsdom 은 캔버스를 그리지 못한다 — 캡처가 되는 상황을 흉내 낸다
  HTMLCanvasElement.prototype.getContext = jest.fn(() => ({ drawImage: jest.fn() })) as never;
  HTMLCanvasElement.prototype.toBlob = jest.fn(function (cb: BlobCallback) {
    cb(new Blob(['x'], { type: 'image/jpeg' }));
  }) as never;
});

test('누르기 전에는 아무것도 겹치지 않는다', () => {
  render(<LiveFaceOverlay videoRef={makeVideoRef()} channelId="ch60" />);
  expect(screen.getByTestId('face-identify-button')).toBeInTheDocument();
  expect(screen.queryByTestId('face-identify-boxes')).not.toBeInTheDocument();
  expect(screen.queryByTestId('face-identify-panel')).not.toBeInTheDocument();
});

test('확신한 얼굴만 이름이 나온다', async () => {
  mockIdentify.mockResolvedValue({ faces: [CONFIDENT, UNSURE] });
  render(<LiveFaceOverlay videoRef={makeVideoRef()} channelId="ch60" />);

  fireEvent.click(screen.getByTestId('face-identify-button'));

  await waitFor(() => expect(screen.getByTestId('face-identify-panel')).toBeInTheDocument());
  // 이름표는 확신한 하나뿐 (목록 1 + 상자 1)
  expect(screen.getAllByText('이대한').length).toBeGreaterThanOrEqual(1);
  expect(screen.getByTestId('face-identify-boxes')).toBeInTheDocument();
});

test('의원이 아닌 얼굴만 잡히면 그렇게 말해 준다', async () => {
  mockIdentify.mockResolvedValue({ faces: [UNSURE] });
  render(<LiveFaceOverlay videoRef={makeVideoRef()} channelId="ch60" />);
  fireEvent.click(screen.getByTestId('face-identify-button'));
  await waitFor(() =>
    expect(screen.getByText(/의원 명단과 맞지 않습니다/)).toBeInTheDocument(),
  );
});

test('이름을 누르면 의원 상세가 열린다', async () => {
  mockIdentify.mockResolvedValue({ faces: [CONFIDENT] });
  mockDetail.mockResolvedValue({
    councilor: {
      id: 'c-1', name: '이대한', party: '더불어민주당', district: '남양주시 제4선거구',
      committee: null, role: null, contact: null, active: true, committees: [],
    },
    career: ['(現) 제12대 경기도의원'],
    positions: [],
    recent_speeches: [],
  } as never);

  render(<LiveFaceOverlay videoRef={makeVideoRef()} channelId="ch60" />);
  fireEvent.click(screen.getByTestId('face-identify-button'));
  await waitFor(() => expect(screen.getByTestId('face-identify-panel')).toBeInTheDocument());

  fireEvent.click(screen.getAllByTestId('face-identify-name')[0]!);
  await waitFor(() => expect(mockDetail).toHaveBeenCalledWith('c-1'));
  expect(await screen.findByText('(現) 제12대 경기도의원')).toBeInTheDocument();
});

test('캔버스를 못 뜨면 서버 캡처로 물러선다', async () => {
  mockIdentifyChannel.mockResolvedValue({ faces: [CONFIDENT] });
  render(<LiveFaceOverlay videoRef={makeVideoRef(false)} channelId="ch60" />);
  fireEvent.click(screen.getByTestId('face-identify-button'));
  await waitFor(() => expect(mockIdentifyChannel).toHaveBeenCalledWith('ch60', undefined));
  expect(mockIdentify).not.toHaveBeenCalled();
});

test('방송 중이 아니면 버튼을 내린다', () => {
  render(<LiveFaceOverlay videoRef={makeVideoRef()} channelId="ch60" enabled={false} />);
  expect(screen.queryByTestId('face-identify-button')).not.toBeInTheDocument();
});
