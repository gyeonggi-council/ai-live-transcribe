/**
 * 공통 유틸리티 바 — 경기도의회 업무플랫폼 전 서비스 최상단 동일 노출.
 *
 * 링크 목록의 **정본은 D:\260712_경기도의회_시스템구축\design\ggc-nav.json** 이다.
 * 항목·순서·문구를 여기서 임의로 바꾸지 말 것 — 정본을 고친 뒤 check_nav.py 로 대조한다.
 *   python D:\260712_경기도의회_시스템구축\design\check_nav.py --service ggc-ai-live-transcribe
 *
 * 스타일은 정본 토큰(src/app/ggc-tokens.css `.ggc-utility-bar`)이 전부 가진다 —
 * 클래스·마크업 구조를 바꾸지 않는다(참조 마크업: ggc_sso/app/static/index.html).
 *
 * ★타 서비스 링크는 전부 **절대경로 <a href>** 다. 이 앱은 basePath=/transcribe 로
 *   빌드되므로 next/link 를 쓰면 /transcribe/award/ 처럼 접두어가 겹친다(raw <a> 는 안 겹친다).
 * 서버 컴포넌트다. 상태도 이벤트도 없다.
 */
export default function UtilityBar() {
  return (
    <div className="ggc-utility-bar">
      <div className="inner">
        <a className="brand" href="/index">
          경기도의회 업무플랫폼
        </a>
        <nav aria-label="통합서비스">
          <span className="label">통합서비스</span>
          <a href="/index">문서 허브</a>
          <a className="active" aria-current="page" href="/transcribe/">
            실시간 자막
          </a>
          <a href="/award/">표창관리</a>
          <a href="/hr/">인사관리</a>
          <a href="/aide/">의원 AI 비서</a>
          <a href="/kb/">지식창고</a>
          <a href="/budget/">예산 집행현황</a>
          <a href="/domain/">도메인 관리</a>
          <a href="/press/">보도자료 배포</a>
          <a href="/ordinance/">조례 생성·검토</a>
          <a href="/audit/">행정사무감사</a>
          <a href="/hermes/">헤르메스</a>
          <a href="/bill-system/">의안처리 시연</a>
          <a href="/ops/">운영 포털</a>
          <a href="https://ggc-schedule.vercel.app" target="_blank" rel="noreferrer">
            의사일정관리
          </a>
          <a href="https://ggc-hipass.vercel.app" target="_blank" rel="noreferrer">
            하이패스 경비정산
          </a>
          <span className="disabled" title="내부망 전용">
            입법역량지원(내부망)
          </span>
        </nav>
      </div>
    </div>
  );
}
