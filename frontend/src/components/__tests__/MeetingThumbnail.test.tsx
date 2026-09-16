import { fireEvent, render, screen } from '@testing-library/react';

import MeetingThumbnail from '../MeetingThumbnail';

const base = { id: 'f2df9d15-1216-424d-b588-c9ad4bbcd3a2' };

describe('MeetingThumbnail', () => {
  it('VOD 가 있으면 서버 썸네일 API 이미지를 그린다', () => {
    const { container } = render(
      <MeetingThumbnail meeting={{ ...base, vod_url: 'https://kms/x.mp4' }} label="도시환경위원회" />,
    );
    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toMatch(/\/api\/meetings\/f2df9d15-.*\/thumbnail$/);
    expect(screen.queryByText('도시환경위원회')).toBeNull();
  });

  it('VOD 가 없으면 위원회명 자리표시', () => {
    const { container } = render(
      <MeetingThumbnail meeting={{ ...base, vod_url: null }} label="본회의" />,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('본회의')).toBeInTheDocument();
  });

  it('이미지를 못 받으면 자리표시로 떨어진다', () => {
    const { container } = render(
      <MeetingThumbnail meeting={{ ...base, vod_url: 'https://kms/x.mp4' }} label="본회의" />,
    );
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('본회의')).toBeInTheDocument();
  });
});
