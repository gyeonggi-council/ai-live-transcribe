import { coarsenLiveSpeaker } from '../speakerLabel';

describe('coarsenLiveSpeaker (라이브 화자 기관 구분 표기)', () => {
  it('의원·위원장 등 의회 구성원은 도의원으로 표시한다', () => {
    expect(coarsenLiveSpeaker('박순희 위원')).toBe('도의원');
    expect(coarsenLiveSpeaker('국중범 위원장')).toBe('도의원');
    expect(coarsenLiveSpeaker('이자형 의원')).toBe('도의원');
    expect(coarsenLiveSpeaker('김진경 의장')).toBe('도의원');
    expect(coarsenLiveSpeaker('부위원장')).toBe('도의원');
  });

  it('집행부 접두어·직책 라벨은 집행부로 표시한다', () => {
    expect(coarsenLiveSpeaker('집행부 유보통합준비단장')).toBe('집행부');
    expect(coarsenLiveSpeaker('엄신옥 유보통합준비단장')).toBe('집행부');
    expect(coarsenLiveSpeaker('고아영 학교교육국장')).toBe('집행부');
    expect(coarsenLiveSpeaker('전대석 기획조정실장')).toBe('집행부');
    expect(coarsenLiveSpeaker('김동연 지사')).toBe('집행부');
    expect(coarsenLiveSpeaker('임태희 교육감')).toBe('집행부');
  });

  it('미상 화자(화자 N)와 판정 불가 라벨은 숨긴다(null)', () => {
    expect(coarsenLiveSpeaker('화자 3')).toBeNull();
    expect(coarsenLiveSpeaker('홍길동')).toBeNull();
    expect(coarsenLiveSpeaker('')).toBeNull();
    expect(coarsenLiveSpeaker(null)).toBeNull();
    expect(coarsenLiveSpeaker(undefined)).toBeNull();
  });
});
