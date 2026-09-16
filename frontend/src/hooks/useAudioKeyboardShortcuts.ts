import { useCallback, useEffect, useRef } from 'react';

interface AudioKeyboardShortcutsOptions {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onSave?: () => void;
  onSplitSpeaker?: () => void;
  enabled?: boolean;
}

/**
 * 속기 키보드 단축키 훅
 *
 * - F5 / Ctrl+Space: 재생/일시정지
 * - F6 / Ctrl+←: 5초 되감기
 * - F7 / Ctrl+→: 5초 앞으로
 * - F8: 누르고 있으면 0.5배속, 놓으면 원래 속도
 * - Ctrl+S: 저장
 * - Ctrl+Enter: 화자 분리
 */
export default function useAudioKeyboardShortcuts({
  videoRef,
  onSave,
  onSplitSpeaker,
  enabled = true,
}: AudioKeyboardShortcutsOptions) {
  const savedPlaybackRate = useRef(1);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return;

      const video = videoRef.current;
      const isCtrl = e.ctrlKey || e.metaKey;

      // F5 or Ctrl+Space: 재생/일시정지
      if (e.key === 'F5' || (isCtrl && e.code === 'Space')) {
        e.preventDefault();
        if (video) {
          if (video.paused) {
            video.play();
          } else {
            video.pause();
          }
        }
        return;
      }

      // F6 or Ctrl+←: 5초 되감기
      if (e.key === 'F6' || (isCtrl && e.key === 'ArrowLeft')) {
        e.preventDefault();
        if (video) {
          video.currentTime = Math.max(0, video.currentTime - 5);
        }
        return;
      }

      // F7 or Ctrl+→: 5초 앞으로
      if (e.key === 'F7' || (isCtrl && e.key === 'ArrowRight')) {
        e.preventDefault();
        if (video) {
          video.currentTime = Math.min(
            video.duration || Infinity,
            video.currentTime + 5
          );
        }
        return;
      }

      // F8: 누르고 있으면 0.5배속
      if (e.key === 'F8' && !e.repeat) {
        e.preventDefault();
        if (video) {
          savedPlaybackRate.current = video.playbackRate;
          video.playbackRate = 0.5;
        }
        return;
      }

      // Ctrl+S: 저장
      if (isCtrl && e.key === 's') {
        e.preventDefault();
        onSave?.();
        return;
      }

      // Ctrl+Enter: 화자 분리
      if (isCtrl && e.key === 'Enter') {
        e.preventDefault();
        onSplitSpeaker?.();
        return;
      }
    },
    [enabled, videoRef, onSave, onSplitSpeaker]
  );

  const handleKeyUp = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return;

      // F8 놓으면 원래 속도 복원
      if (e.key === 'F8') {
        e.preventDefault();
        const video = videoRef.current;
        if (video) {
          video.playbackRate = savedPlaybackRate.current;
        }
      }
    },
    [enabled, videoRef]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [handleKeyDown, handleKeyUp]);
}
