'use client';

import type { RefObject } from 'react';
import React, { useCallback, useState } from 'react';

import Card from '@/components/ui/Card';
import type { CouncilorType } from '@/types';

import Mp4Player from './Mp4Player';
import VideoControls from './VideoControls';


/** 정당별 컬러 매핑 */
function getPartyBadgeClass(party: string | null): string {
  if (!party) return 'bg-gray-100 text-gray-600';
  if (party.includes('민주')) return 'bg-party-dem/10 text-party-dem';
  if (party.includes('국민의힘')) return 'bg-party-pp/10 text-party-pp';
  if (party.includes('정의')) return 'bg-warning-bg/20 text-warning';
  return 'bg-gray-100 text-gray-600';
}

function formatTimeLarge(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n: number) => n.toString().padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

interface AudioPlayerPanelProps {
  vodUrl: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  currentTime: number;
  duration: number;
  onTimeUpdate: (time: number) => void;
  onError?: (error: Error) => void;
  currentSpeaker?: string | null;
  currentCouncilor?: CouncilorType | null;
}

/**
 * 강화된 오디오/비디오 플레이어 패널 (속기 모드 우측)
 *
 * - 비디오 플레이어
 * - 배속 버튼 그룹 (0.5x ~ 2x)
 * - 대형 시간 표시
 * - 현재 발언자 의원 카드 (사진 + 정당 배지)
 * - 키보드 단축키 안내
 */
export default function AudioPlayerPanel({
  vodUrl,
  videoRef,
  currentTime,
  duration,
  onTimeUpdate,
  onError,
  currentSpeaker,
  currentCouncilor,
}: AudioPlayerPanelProps) {
  const [playbackRate, setPlaybackRate] = useState(1);

  const handleSpeedChange = useCallback(
    (speed: number) => {
      setPlaybackRate(speed);
      if (videoRef.current) {
        videoRef.current.playbackRate = speed;
      }
    },
    [videoRef]
  );

  return (
    <div className="flex flex-col h-full gap-3">
      {/* 비디오 플레이어 */}
      <div className="rounded-lg overflow-hidden bg-black">
        <Mp4Player
          vodUrl={vodUrl}
          videoRef={videoRef}
          onTimeUpdate={onTimeUpdate}
          onError={onError}
        />
        <VideoControls
          videoRef={videoRef}
          currentTime={currentTime}
          duration={duration}
        />
      </div>

      {/* 대형 시간 표시 + 배속 컨트롤 */}
      <Card padding="sm">
        <div className="text-center mb-2">
          <span className="text-2xl font-mono font-semibold text-gray-900 tabular-nums">
            {formatTimeLarge(currentTime)}
          </span>
          <span className="text-sm text-gray-400 mx-1">/</span>
          <span className="text-sm font-mono text-gray-400 tabular-nums">
            {formatTimeLarge(duration)}
          </span>
        </div>
        <div className="flex items-center justify-center gap-1">
          {SPEED_OPTIONS.map((speed) => (
            <button
              key={speed}
              onClick={() => handleSpeedChange(speed)}
              className={`px-2 py-1 text-xs rounded font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                playbackRate === speed
                  ? 'bg-primary text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {speed}x
            </button>
          ))}
        </div>
      </Card>

      {/* 현재 발언자 카드 (강화) */}
      {currentSpeaker && (
        <Card padding="sm">
          <p className="text-xs text-gray-500 mb-2">현재 발언자</p>
          <div className="flex items-center gap-3">
            {currentCouncilor?.profile_image_url ? (
              <img
                src={currentCouncilor.profile_image_url}
                alt={currentSpeaker}
                className="w-12 h-12 rounded-full object-cover flex-shrink-0"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            ) : (
              <div className="w-12 h-12 rounded-full bg-primary-10 flex items-center justify-center flex-shrink-0">
                <span className="text-lg font-medium text-primary">
                  {currentSpeaker.charAt(0)}
                </span>
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-gray-900 truncate">
                {currentSpeaker}
              </p>
              {currentCouncilor && (
                <>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${getPartyBadgeClass(currentCouncilor.party)}`}>
                      {currentCouncilor.party}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5 truncate">
                    {[
                      currentCouncilor.district,
                      currentCouncilor.committee,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* 키보드 단축키 가이드 */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs text-gray-500 space-y-1">
        <p className="font-medium text-gray-700 mb-1.5">단축키</p>
        <div className="grid grid-cols-2 gap-1">
          <span>
            <kbd className="px-1 py-0.5 bg-white border border-gray-300 rounded text-xs">F5</kbd> 재생/정지
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-white border border-gray-300 rounded text-xs">F6</kbd> 5초 뒤로
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-white border border-gray-300 rounded text-xs">F7</kbd> 5초 앞으로
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-white border border-gray-300 rounded text-xs">F8</kbd> 느리게 재생
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-white border border-gray-300 rounded text-xs">Ctrl+S</kbd> 저장
          </span>
          <span>
            <kbd className="px-1 py-0.5 bg-white border border-gray-300 rounded text-xs">Ctrl+Enter</kbd> 화자 분리
          </span>
        </div>
      </div>
    </div>
  );
}
