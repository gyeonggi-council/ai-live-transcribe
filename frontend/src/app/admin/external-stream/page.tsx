'use client';

import { useState } from 'react';

import { useRouter } from 'next/navigation';

import PageHeader from '@/components/PageHeader';
import RoleGuard from '@/components/RoleGuard';
import { Button, Input } from '@/components/ui';
import { startChannelStt, stopChannelStt } from '@/lib/api';

const EXT_TEST_CHANNEL = 'chT1';

function ExternalStreamTester() {
  const router = useRouter();
  const [url, setUrl] = useState('');
  const [status, setStatus] = useState<'idle' | 'starting' | 'running' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    if (!url.trim()) return;
    setStatus('starting');
    setError(null);
    try {
      const result = await startChannelStt(EXT_TEST_CHANNEL, { streamUrl: url.trim() });
      if (result.status === 'already_running') {
        // 이미 실행 중이면 먼저 중지 후 재시작
        await stopChannelStt(EXT_TEST_CHANNEL);
        await startChannelStt(EXT_TEST_CHANNEL, { streamUrl: url.trim() });
      }
      setStatus('running');
      // 테스트 채널 페이지로 자동 이동
      router.push(`/live?channel=${EXT_TEST_CHANNEL}`);
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleStop = async () => {
    try {
      await stopChannelStt(EXT_TEST_CHANNEL);
      setStatus('idle');
    } catch (err) {
      console.error('Failed to stop external stream STT:', err);
    }
  };

  return (
    <div className="p-6">
      <div className="max-w-3xl mx-auto">
        <PageHeader
          eyebrow="ADMIN"
          title="외부 스트림 테스트"
          description={`외부 HLS 스트림 URL(국회 생중계 등)을 입력해 실시간 자막을 테스트합니다. 테스트 채널(${EXT_TEST_CHANNEL})을 사용합니다.`}
        />
        <div
          className="p-4 bg-surface-raised border border-border rounded-lg"
          data-testid="ext-stream-panel"
        >
          <div className="flex gap-2">
            <div className="flex-1">
              <Input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://assembly.webcast.go.kr/main/player.asp?xcode=37&xcgcd=..."
                data-testid="ext-stream-url-input"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleStart();
                }}
              />
            </div>
            <Button
              onClick={handleStart}
              disabled={!url.trim() || status === 'starting'}
              loading={status === 'starting'}
              variant="primary"
              size="md"
              className="whitespace-nowrap"
              data-testid="ext-stream-start-btn"
            >
              {status === 'starting' ? 'STT 시작 중...' : 'STT 시작'}
            </Button>
            {status === 'running' && (
              <button
                onClick={handleStop}
                className="px-4 py-2 text-sm font-medium text-error bg-error/5 hover:bg-error/10 border border-error/30 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                data-testid="ext-stream-stop-btn"
              >
                중지
              </button>
            )}
          </div>
          {status === 'running' && (
            <div className="mt-2 flex items-center gap-2 text-sm text-success">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
              </span>
              실행 중 ({EXT_TEST_CHANNEL}) — 자동으로 채널 페이지로 이동합니다
            </div>
          )}
          {status === 'error' && error && (
            <div className="mt-2 text-sm text-error">오류: {error}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ExternalStreamAdminPage() {
  return (
    <RoleGuard roles={['admin']}>
      <ExternalStreamTester />
    </RoleGuard>
  );
}
