'use client';

import React, { useRef, useState } from 'react';

import { Button, Callout } from '@/components/ui';
import { API_BASE_URL } from '@/lib/api';
import { getToken } from '@/lib/auth';

export interface VodUploadModalProps {
  open: boolean;
  onClose: () => void;
  meetingId: string;
  meetingTitle: string;
  vodUrl: string | null;
  /** 현재 subtitle_stage (reviewing/final이면 경고 + force 확인) */
  currentStage?: 'none' | 'draft' | 'ai' | 'reviewing' | 'final';
  onSuccess?: (subtitlesCount: number) => void;
}

type Phase = 'idle' | 'uploading' | 'processing' | 'done' | 'error';

export default function VodUploadModal({
  open,
  onClose,
  meetingId,
  meetingTitle,
  vodUrl,
  currentStage = 'none',
  onSuccess,
}: VodUploadModalProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState(0); // 0..100
  const [file, setFile] = useState<File | null>(null);
  const [resultMsg, setResultMsg] = useState<string>('');
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  if (!open) return null;

  const reset = () => {
    setPhase('idle');
    setProgress(0);
    setFile(null);
    setResultMsg('');
    xhrRef.current?.abort();
    xhrRef.current = null;
  };

  const handleClose = () => {
    if (phase === 'uploading' || phase === 'processing') {
      if (!confirm('업로드를 취소하시겠습니까?')) return;
    }
    reset();
    onClose();
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const startUpload = () => {
    if (!file) return;

    const token = getToken();
    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;

    xhr.upload.addEventListener('progress', (ev) => {
      if (ev.lengthComputable) {
        setProgress(Math.round((ev.loaded / ev.total) * 100));
      }
    });

    xhr.upload.addEventListener('load', () => {
      setPhase('processing');
      setResultMsg('OpenAI에서 자막 생성 중 (약 5~10분)...');
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          setPhase('done');
          setResultMsg(`✅ ${data.subtitles_count ?? 0}개 자막 생성 완료!`);
          onSuccess?.(data.subtitles_count ?? 0);
        } catch {
          setPhase('error');
          setResultMsg('응답 파싱 실패');
        }
      } else {
        setPhase('error');
        try {
          const data = JSON.parse(xhr.responseText);
          setResultMsg(`실패: ${data.detail || xhr.status}`);
        } catch {
          setResultMsg(`실패: HTTP ${xhr.status}`);
        }
      }
    });

    xhr.addEventListener('error', () => {
      setPhase('error');
      setResultMsg('네트워크 오류');
    });

    xhr.addEventListener('abort', () => {
      setPhase('idle');
      setResultMsg('업로드 취소됨');
      setProgress(0);
    });

    const fd = new FormData();
    fd.append('file', file);

    // reviewing/final 단계는 서버에서 409 차단됨. force=true로 재시도하려면
    // 사용자 confirm을 먼저 받음.
    let endpoint = `${API_BASE_URL}/api/meetings/${meetingId}/upload-audio-stt`;
    if (currentStage === 'reviewing' || currentStage === 'final') {
      const ok = confirm(
        `현재 단계(${currentStage})에서 업로드 시 속기사 교정본이 덮어쓰여집니다.\n` +
          `정말 강제로 진행하시겠습니까?`,
      );
      if (!ok) {
        setPhase('idle');
        return;
      }
      endpoint += '?force=true';
    }

    xhr.open('POST', endpoint);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.timeout = 30 * 60 * 1000; // 30 min

    setPhase('uploading');
    setProgress(0);
    setResultMsg('');
    xhr.send(fd);
  };

  const fileSizeMB = file ? file.size / (1024 * 1024) : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={handleClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4 p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">🎙 MP3 업로드 → AI 자막 생성</h2>
            <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{meetingTitle}</p>
          </div>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
            aria-label="닫기"
          >
            ✕
          </button>
        </div>

        {(currentStage === 'reviewing' || currentStage === 'final') && (
          <Callout variant="danger" className="p-3 text-xs">
            현재 단계: <strong>{currentStage}</strong> — 속기사 교정본이 있습니다.
            업로드 시 덮어쓰여집니다.
          </Callout>
        )}

        {/* Step 1: 오디오 파일 준비 안내 */}
        {phase === 'idle' && !file && (
          <div className="space-y-3">
            <Callout variant="info" title="1단계: 오디오 파일 준비" className="p-3">
              <ol className="text-xs space-y-1 list-decimal list-inside">
                <li>KMS, 녹음 장비, 또는 MP4 영상에서 <strong>MP3/M4A/WAV</strong> 오디오 추출</li>
                <li>오디오 파일은 MP4 영상보다 <strong>~10배 작음</strong> (2시간 회의 ≈ 100MB)</li>
                <li>KMS에서 MP4를 다운로드한 경우 ffmpeg 등으로 오디오만 추출 가능</li>
              </ol>
              {vodUrl && (
                <a
                  href={vodUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block mt-2 px-3 py-1.5 text-xs font-medium bg-primary text-white rounded-md hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  ↗ KMS 영상 열기
                </a>
              )}
            </Callout>

            <Callout variant="success" title="2단계: 오디오 파일 선택 (MP3/M4A/WAV/MP4)" className="p-3">
              <input
                type="file"
                accept="audio/mpeg,audio/mp4,audio/wav,video/mp4,.mp3,.m4a,.wav,.mp4"
                onChange={handleFileSelect}
                className="block w-full text-xs text-gray-700 file:mr-2 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-medium file:bg-success file:text-white hover:file:bg-success/90"
              />
              <p className="text-xs text-gray-600 mt-1.5">
                ※ MP3가 가장 빠르고 작습니다. MP4도 허용(오디오 자동 추출).
              </p>
            </Callout>
          </div>
        )}

        {/* File selected, ready to upload */}
        {phase === 'idle' && file && (
          <div className="space-y-3">
            <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-sm">
              <p className="font-medium text-gray-900">선택된 파일:</p>
              <p className="text-xs text-gray-600 truncate">{file.name}</p>
              <p className="text-xs text-gray-500 mt-1">{fileSizeMB.toFixed(1)} MB</p>
            </div>
            <div className="flex gap-2">
              <Button onClick={startUpload} className="flex-1">
                🚀 업로드 + 자막 생성 시작
              </Button>
              <Button variant="outline" onClick={() => setFile(null)}>
                다시 선택
              </Button>
            </div>
            <p className="text-xs text-gray-500">
              예상 시간: 업로드 5~10분 + OpenAI 처리 5~10분
            </p>
          </div>
        )}

        {/* Uploading */}
        {phase === 'uploading' && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-900">업로드 중... {progress}%</p>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-primary h-2 rounded-full transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-xs text-gray-500">
              {((fileSizeMB * progress) / 100).toFixed(0)} / {fileSizeMB.toFixed(0)} MB
            </p>
            <button
              onClick={() => xhrRef.current?.abort()}
              className="text-xs text-error hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
            >
              취소
            </button>
          </div>
        )}

        {/* Processing (OpenAI 배치 전사) */}
        {phase === 'processing' && (
          <div className="space-y-2 text-center py-4">
            <div className="inline-block w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
            <p className="text-sm font-medium text-gray-900">OpenAI 자막 생성 중</p>
            <p className="text-xs text-gray-500">{resultMsg}</p>
            <p className="text-xs text-gray-400">
              ※ 이 창을 닫아도 서버에서 계속 처리됩니다 (약 5~10분)
            </p>
          </div>
        )}

        {/* Done */}
        {phase === 'done' && (
          <div className="space-y-3">
            <Callout variant="success" className="p-3">
              <p className="font-medium text-gray-900">{resultMsg}</p>
              <p className="text-xs text-gray-600 mt-1">
                AI 문법 교정이 백그라운드로 진행 중입니다.
              </p>
            </Callout>
            <Button onClick={handleClose} className="w-full">
              닫기
            </Button>
          </div>
        )}

        {/* Error */}
        {phase === 'error' && (
          <div className="space-y-3">
            <Callout variant="danger" className="p-3">
              {resultMsg}
            </Callout>
            <div className="flex gap-2">
              <Button onClick={reset} className="flex-1">
                다시 시도
              </Button>
              <Button variant="outline" onClick={handleClose}>
                닫기
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
