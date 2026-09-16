import { recordingByteRange } from '../useRecordingSegmentPlayer';

describe('recordingByteRange — 자막 시각 → 녹음 파일 바이트', () => {
  it('세션 목록이 없으면 start_offset_sec 기준 선형 매핑 (앞 2KB·뒤 4KB 여유)', () => {
    const r = recordingByteRange(
      { bytes_per_sec: 6000, size_bytes: 1_000_000, start_offset_sec: 0 },
      10,
      15,
    );
    expect(r).toEqual({ startByte: 60_000 - 2048, endByte: 90_000 + 4096 });
  });

  it('녹음이 회의 중간부터면 오프셋만큼 당긴다', () => {
    const r = recordingByteRange(
      { bytes_per_sec: 6000, size_bytes: 1_000_000, start_offset_sec: 5 },
      10,
      15,
    );
    expect(r?.startByte).toBe(30_000 - 2048);
  });

  it('서버 재시작으로 시계가 0 으로 되감긴 파일은 최신 세션으로 매핑한다 (2026-09-01 결함)', () => {
    const meta = {
      bytes_per_sec: 6000,
      size_bytes: 1_200_000,
      sessions: [
        { clock: 0, byte: 0 },
        { clock: 0, byte: 600_000 },
      ],
    };
    const r = recordingByteRange(meta, 50, 55);
    expect(r?.startByte).toBe(600_000 + 300_000 - 2048);
  });

  it('운영 회의 70ebdfbb 의 세션표 — 첫 자막(9.02초)은 파일 앞쪽, 뒤 세션 시각은 그 세션 바이트로', () => {
    const meta = {
      bytes_per_sec: 6000,
      size_bytes: 202_566_480,
      start_offset_sec: 0,
      sessions: [
        { clock: 0.0, byte: 0 },
        { clock: 8096.83, byte: 49_764_716 },
        { clock: 13684.19, byte: 83_327_848 },
      ],
    };
    expect(recordingByteRange(meta, 9.02, 13.42)?.startByte).toBe(Math.floor(9.02 * 6000) - 2048);
    const late = recordingByteRange(meta, 8100, 8105);
    expect(late?.startByte).toBe(Math.floor(49_764_716 + (8100 - 8096.83) * 6000) - 2048);
  });

  it('녹음이 아직 그 구간까지 안 왔으면 null', () => {
    expect(
      recordingByteRange({ bytes_per_sec: 6000, size_bytes: 60_000 }, 100, 105),
    ).toBeNull();
  });

  it('끝 바이트는 파일 크기를 넘지 않는다', () => {
    const r = recordingByteRange({ bytes_per_sec: 6000, size_bytes: 100_000 }, 15, 30);
    expect(r?.endByte).toBe(99_999);
  });
});
