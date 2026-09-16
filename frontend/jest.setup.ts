import '@testing-library/jest-dom';
import { toHaveNoViolations } from 'jest-axe';

expect.extend(toHaveNoViolations);

// jsdom 에는 objectURL 이 없다 — 클립 미리보기·썸네일이 blob 을 <video>/<img> 에 거는 경로를
// 테스트하려면 이것이 있어야 한다(없으면 TypeError 가 나고 컴포넌트가 오류 분기로 떨어진다).
if (typeof URL.createObjectURL !== 'function') {
  let n = 0;
  URL.createObjectURL = jest.fn(() => `blob:jest/${++n}`);
  URL.revokeObjectURL = jest.fn();
}
