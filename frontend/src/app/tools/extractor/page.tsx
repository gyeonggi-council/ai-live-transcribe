'use client';

import React, { useEffect, useState } from 'react';

import { useSearchParams } from 'next/navigation';

import Link from 'next/link';

import PageHeader from '@/components/PageHeader';
import { API_BASE_URL, getExtractorVersion } from '@/lib/api';
import type { ExtractorVersionType } from '@/types';

/**
 * /tools/extractor — 영상추출기 공개 다운로드 페이지 (가드 없음)
 *
 * 경기도의회 영상추출기: 회의 영상에서 발언 구간을 mp4로 추출하는 데스크톱 앱.
 * 설치된 앱은 version.json 폴링으로 자동 업데이트된다.
 *
 * 2026-09-03 에 웹 워크벤치(/clips)로 대체하며 종료 안내로 바꿨다가 2026-09-08 사용자 결정으로
 * 되살렸다(v1.10 — 의회 검증환경 서버로 연결). 웹 워크벤치와 병행한다.
 * ★설치파일은 의회 서버(/api/tools/extractor/download, PVC 보관)에서 받는 것이 기본이고,
 *  GitHub Releases(ggc-extractor-releases)에도 같은 파일을 올려 둔다(의회망 밖·서버 점검 중 대안).
 *  버전 정보(현재 버전·릴리스 노트)는 백엔드 version.json 에서 best-effort 로 조회해 표시한다.
 *
 * ?midx=N 파라미터: 발언영상(clips) 페이지에서 프로토콜 실행이 안 될 때 넘어오는
 * 경로 — 설치 후 「추출기에서 회의 열기 재시도」로 이어준다.
 */

// GitHub 'latest' 안정 링크 — asset 이름 고정이라 새 버전 배포 시 자동으로 최신을 가리킨다.
const GITHUB_RELEASES = 'https://github.com/gyeonggi-council/ggc-extractor-releases/releases/latest';
const GITHUB_DOWNLOAD = `${GITHUB_RELEASES}/download/GgcExtractorSetup.exe`;
// 서버 다운로드 — basePath(/transcribe)가 붙는 API 주소로. 상대경로 '/api/…' 는 접두어가 빠져 404 다.
const SERVER_DOWNLOAD = `${API_BASE_URL}/api/tools/extractor/download`;

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('ko-KR');
}

function ExtractorDownloadContent() {
  const searchParams = useSearchParams();
  const midxParam = searchParams.get('midx');
  const midx = midxParam && /^\d+$/.test(midxParam) ? midxParam : null;

  const [manifest, setManifest] = useState<ExtractorVersionType | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getExtractorVersion()
      .then(setManifest)
      .catch(() => setManifest(null))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6">
      <div className="max-w-2xl mx-auto">
        <PageHeader
          title="경기도의회 영상추출기"
          description="회의 영상에서 원하는 구간을 mp4로 추출하는 데스크톱 앱"
        />

        {midx && (
          <section
            data-testid="midx-notice"
            className="p-5 rounded-lg border border-brand/40 bg-brand/5 mb-4"
          >
            <p className="text-sm text-text leading-relaxed mb-3">
              발언영상 페이지에서 오셨나요? 추출기가 아직 설치되어 있지 않다면 아래에서
              설치한 뒤 다시 시도하세요. 설치되어 있다면 바로 열 수 있습니다.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <a
                data-testid="retry-open"
                href={`ggcextractor://open?midx=${midx}`}
                className="inline-block px-4 py-2 rounded-md bg-brand text-white text-sm hover:opacity-90"
              >
                ✂ 추출기에서 회의 열기 재시도
              </a>
              <span className="text-xs text-text-muted">영상 번호(midx): {midx}</span>
            </div>
          </section>
        )}

        <section className="p-5 rounded-lg border border-border bg-surface mb-4">
          <p className="text-sm text-text-secondary leading-relaxed">
            경기도의회 회의 영상(생중계 VOD)에서 의원별 발언 구간 등 원하는
            구간을 골라 mp4 파일로 추출하는 Windows용 데스크톱 프로그램입니다.
            AI 자막으로 분석된 발언 구간을 자동으로 불러와 클릭 몇 번으로 영상
            클립을 만들 수 있습니다.
          </p>
          <p className="mt-2 text-sm text-text-secondary leading-relaxed" data-testid="web-alternative">
            설치 없이 브라우저에서 바로 자르려면{' '}
            <Link href="/clips" className="text-primary underline">
              발언영상 추출 화면
            </Link>
            을 쓰세요. 두 방법은 같은 회의 목록·발언 구간을 봅니다.
          </p>
        </section>

        {/* 응용프로그램 제어 정책으로 exe 가 막히는 PC 를 위한 길 (2026-09-10).
            경로를 Program Files 로 옮겨도 같은 오류가 나는 것을 실측했다 — 서명 기준이다. */}
        <section
          data-testid="webapp-install"
          className="p-5 rounded-lg border border-border bg-surface mb-4"
        >
          <h2 className="text-base font-semibold text-text mb-3">
            설치가 차단되면 — 웹앱으로 설치하세요
          </h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            일부 업무용 PC 는 보안 정책이 허용 목록에 없는 프로그램의 실행을 막습니다.
            설치 마지막 단계에서 <span className="text-text">「CreateProcess 실패 · 애플리케이션 제어 정책에서
            이 파일을 차단했습니다」</span> 가 뜨면 그 경우입니다.
          </p>
          <p className="mt-2 text-sm text-text-secondary leading-relaxed">
            그럴 때는 <span className="text-text">이 자막서비스를 웹앱으로 설치</span>하면 됩니다.
            바탕화면 아이콘과 독립 창이 생겨 설치형 프로그램처럼 쓰지만, 새 프로그램이 아니라
            브라우저 안에서 도는 것이라 정책에 걸리지 않습니다.
          </p>
          <ul className="mt-3 space-y-1.5 text-sm text-text-secondary">
            <li>
              <span className="text-text font-medium">Edge</span> — 주소창 오른쪽의 설치 아이콘,
              또는 오른쪽 위 <span className="tabular-nums">···</span> → 앱 → 이 사이트를 앱으로 설치
            </li>
            <li>
              <span className="text-text font-medium">Chrome</span> — 주소창 오른쪽의 설치 아이콘,
              또는 오른쪽 위 <span className="tabular-nums">⋮</span> → 캐스트·저장 및 공유 → 페이지를 앱으로 설치
            </li>
          </ul>
          <p className="mt-3 text-xs text-text-muted">
            설치한 뒤 작업 표시줄 아이콘을 오른쪽 클릭하면 발언영상 추출·실시간 자막으로 바로 갈 수 있습니다.
            설치형과 달리 처음 한 번 QR 로그인이 필요합니다.
          </p>
        </section>

        <section className="p-5 rounded-lg border border-border bg-surface mb-4">
          <h2 className="text-base font-semibold text-text mb-3">다운로드</h2>

          {/* 버전 정보 — 백엔드에서 best-effort로 표시. 조회 실패해도 다운로드는 가능. */}
          {loading && (
            <div className="mb-2 text-text-muted text-sm">버전 정보 조회 중...</div>
          )}
          {!loading && manifest && (
            <p className="text-sm text-text mb-1">
              현재 버전:{' '}
              <span className="font-semibold tabular-nums">{manifest.version}</span>
              {manifest.published_at && (
                <span className="ml-2 text-xs text-text-muted">
                  ({formatDate(manifest.published_at)} 공개)
                </span>
              )}
            </p>
          )}
          {!loading && manifest?.notes && (
            <p className="text-sm text-text-secondary whitespace-pre-line mb-3">
              {manifest.notes}
            </p>
          )}

          {/* 다운로드 버튼 — 의회 서버(기본) · GitHub Releases(대안) */}
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <a
              href={SERVER_DOWNLOAD}
              data-testid="download-server"
              className="inline-block px-4 py-2 rounded-md bg-brand text-white text-sm hover:opacity-90"
            >
              ⬇ 다운로드 (.exe)
            </a>
            <a
              href={GITHUB_DOWNLOAD}
              data-testid="download-github"
              className="inline-block px-4 py-2 rounded-md border border-border text-text-secondary text-sm hover:bg-surface-raised"
            >
              GitHub 에서 받기 ↗
            </a>
            <a
              href={GITHUB_RELEASES}
              target="_blank"
              rel="noreferrer"
              className="inline-block px-4 py-2 rounded-md border border-border text-text-secondary text-sm hover:bg-surface-raised"
            >
              GitHub 릴리스 페이지 ↗
            </a>
          </div>
          <p className="mt-2 text-xs text-text-muted">
            의회 서버에서 내려받습니다 (별도 로그인 불필요). 서버 점검 중이거나 의회망 밖이면 GitHub 링크를 쓰세요.
          </p>
        </section>

        <p className="text-xs text-text-muted">
          설치된 앱은 새 버전이 배포되면 자동으로 업데이트되므로 다시 내려받을
          필요가 없습니다.
        </p>
      </div>
    </div>
  );
}

export default function ExtractorDownloadPage() {
  return (
    <React.Suspense
      fallback={
        <div className="p-6 text-center text-sm text-text-muted">불러오는 중...</div>
      }
    >
      <ExtractorDownloadContent />
    </React.Suspense>
  );
}
