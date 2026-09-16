'use client';

import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';

import PageHeader from '@/components/PageHeader';
import RoleGuard from '@/components/RoleGuard';
import Button from '@/components/ui/Button';
import Callout from '@/components/ui/Callout';
import Input from '@/components/ui/Input';
import Textarea from '@/components/ui/Textarea';
import { API_BASE_URL, getExtractorVersion, uploadExtractorRelease } from '@/lib/api';
import type { ExtractorVersionType } from '@/types';

/**
 * /admin/tools — 영상추출기 배포 관리 (관리자 전용)
 *
 * 카드1: 현재 배포 버전 (version.json)
 * 카드2: 새 버전 업로드 (.exe 파일 또는 외부 URL)
 * exe 클라이언트는 version.json 을 폴링하여 자동업데이트한다.
 * 2026-09-03 종료 안내로 바꿨다가 2026-09-08 사용자 결정으로 복구(v1.10, 의회 서버 연결).
 * 설치파일은 PVC(/app/data/tools, clips PVC 의 subPath)에 보관돼 재배포에도 남는다.
 */

function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return '—';
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('ko-KR');
}

function ToolsAdmin() {
  // 카드1: 현재 배포 버전
  const [manifest, setManifest] = useState<ExtractorVersionType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  // 카드2: 업로드 폼
  const [version, setVersion] = useState('');
  const [notes, setNotes] = useState('');
  const [mode, setMode] = useState<'file' | 'url'>('file');
  const [file, setFile] = useState<File | null>(null);
  // 업로드 성공 시 증가시켜 파일 input 을 리마운트 — setFile(null)만으로는
  // 네이티브 input 의 표시 파일명이 남는 문제 해결
  const [fileInputKey, setFileInputKey] = useState(0);
  const [externalUrl, setExternalUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setManifest(await getExtractorVersion());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    setSubmitOk(false);

    const v = version.trim();
    if (!v) {
      setSubmitError('버전을 입력하세요 (예: 1.2 또는 1.2.3).');
      return;
    }
    if (mode === 'file' && !file) {
      setSubmitError('설치파일(.exe)을 선택하세요.');
      return;
    }
    if (mode === 'url' && !externalUrl.trim()) {
      setSubmitError('외부 다운로드 URL을 입력하세요.');
      return;
    }

    setSubmitting(true);
    try {
      await uploadExtractorRelease({
        version: v,
        notes: notes.trim(),
        ...(mode === 'file' && file ? { file } : {}),
        ...(mode === 'url' ? { externalUrl: externalUrl.trim() } : {}),
      });
      setSubmitOk(true);
      setVersion('');
      setNotes('');
      setFile(null);
      setFileInputKey((k) => k + 1); // 파일 input 표시 파일명 리셋 (리마운트)
      setExternalUrl('');
      await load(); // 카드1 갱신
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6">
      <div className="max-w-3xl mx-auto">
        <PageHeader
          eyebrow="ADMIN"
          title="영상추출기 배포"
          description="데스크톱 앱(영상추출기) 설치파일 배포와 자동업데이트 채널을 관리합니다."
        />

        {/* 카드1: 현재 배포 버전 */}
        <section
          data-testid="current-release"
          className="mb-6 p-5 rounded-lg border border-border bg-surface"
        >
          <h2 className="text-base font-semibold text-text mb-3">
            현재 배포 버전
          </h2>

          {loading && (
            <div className="py-6 text-center text-text-muted">
              <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2" />
              배포 정보 조회 중...
            </div>
          )}

          {!loading && error && (
            <Callout variant="danger">불러오기 실패: {error}</Callout>
          )}

          {!loading && !error && !manifest && (
            <p className="text-sm text-text-muted">
              배포된 버전이 없습니다. 아래에서 첫 버전을 등록하세요.
            </p>
          )}

          {!loading && !error && manifest && (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-text-muted">버전</dt>
                <dd
                  data-testid="current-version"
                  className="font-semibold text-text tabular-nums"
                >
                  {manifest.version}
                </dd>
                <dt className="text-text-muted">공개일</dt>
                <dd className="text-text">{formatDate(manifest.published_at)}</dd>
                <dt className="text-text-muted">크기</dt>
                <dd className="text-text tabular-nums">
                  {formatSize(manifest.size)}
                </dd>
                <dt className="text-text-muted">SHA-256</dt>
                <dd className="text-text font-mono text-xs">
                  {manifest.sha256 ? manifest.sha256.slice(0, 12) : '—'}
                </dd>
              </dl>

              <div className="mt-4 flex items-center gap-3">
                <a
                  href={`${API_BASE_URL}/api/tools/extractor/download`}
                  className="inline-flex items-center h-8 px-3 rounded-md bg-primary text-white text-sm font-medium transition-colors hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1"
                >
                  설치파일 다운로드
                </a>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowRaw((s) => !s)}
                >
                  version.json 원문 {showRaw ? '숨기기' : '보기'}
                </Button>
              </div>

              {showRaw && (
                <pre className="mt-3 p-3 rounded-md bg-surface-raised border border-border text-xs overflow-x-auto">
                  {JSON.stringify(manifest, null, 2)}
                </pre>
              )}
            </>
          )}
        </section>

        {/* 카드2: 새 버전 업로드 */}
        <section className="p-5 rounded-lg border border-border bg-surface">
          <h2 className="text-base font-semibold text-text mb-3">
            새 버전 업로드
          </h2>

          <form data-testid="upload-form" onSubmit={handleSubmit}>
            <div className="mb-3 max-w-xs">
              <Input
                id="upload-version"
                data-testid="upload-version"
                label="버전 (예: 1.2 또는 1.2.3)"
                type="text"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="1.0.0"
              />
            </div>

            <div className="mb-3">
              <Textarea
                id="upload-notes"
                data-testid="upload-notes"
                label="릴리스 노트"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="변경 사항을 입력하세요"
              />
            </div>

            {/* 파일 업로드 / 외부 URL 라디오 전환 */}
            <div className="mb-3 flex items-center gap-4 text-sm">
              <label className="flex items-center gap-1.5">
                <input
                  data-testid="mode-file"
                  type="radio"
                  name="release-mode"
                  checked={mode === 'file'}
                  onChange={() => setMode('file')}
                  className="accent-primary"
                />
                파일 업로드 (.exe)
              </label>
              <label className="flex items-center gap-1.5">
                <input
                  data-testid="mode-url"
                  type="radio"
                  name="release-mode"
                  checked={mode === 'url'}
                  onChange={() => setMode('url')}
                  className="accent-primary"
                />
                외부 URL
              </label>
            </div>

            {mode === 'file' && (
              <div className="mb-3">
                <input
                  key={fileInputKey}
                  data-testid="upload-file"
                  type="file"
                  accept=".exe"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="text-sm"
                />
              </div>
            )}

            {mode === 'url' && (
              <div className="mb-3">
                <Input
                  data-testid="upload-url"
                  type="url"
                  value={externalUrl}
                  onChange={(e) => setExternalUrl(e.target.value)}
                  placeholder="https://github.com/.../releases/download/v1.0.0/setup.exe"
                />
              </div>
            )}

            <p className="mb-4 text-xs text-text-muted">
              파일 업로드(최대 200MB)는 의회 서버에 보관돼 재배포 뒤에도 남습니다. 같은 파일을
              GitHub Releases(ggc-extractor-releases)에도 올려 두면 의회망 밖에서도 받을 수 있습니다.
            </p>

            {submitError && (
              <Callout variant="danger" className="mb-3">
                {submitError}
              </Callout>
            )}

            {submitOk && (
              <Callout variant="success" className="mb-3">
                새 버전이 배포되었습니다.
              </Callout>
            )}

            <Button
              type="submit"
              data-testid="upload-submit"
              variant="primary"
              loading={submitting}
            >
              {submitting ? '배포 중...' : '배포'}
            </Button>
          </form>
        </section>
      </div>
    </div>
  );
}

export default function AdminToolsPage() {
  return (
    <RoleGuard roles={['admin']}>
      <ToolsAdmin />
    </RoleGuard>
  );
}
