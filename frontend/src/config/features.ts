/**
 * 기능 플래그.
 *
 * KMS_EXPORT_ENABLED — 전자회의록(HWPX)·영상회의록(HTML)·KMS 자동입력(JS) 다운로드 UI 노출 여부.
 * 이 기능은 백엔드(`GET /export?format=hwpx`, `GET /video-minutes`[html|js])가 동작해야 한다.
 * 2026-06-19 백엔드 재시작으로 새 코드 배포 완료 → 노출. (백엔드가 다시 구버전이면 false로 내릴 것)
 * 참고: 영상회의록/KMS 스크립트 다운로드는 LLM 비용이 들어 로그인 필요(미로그인 시 401).
 */
export const KMS_EXPORT_ENABLED = true;
