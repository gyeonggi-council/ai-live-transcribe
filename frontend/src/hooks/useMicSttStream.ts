'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

type MicStatus = 'idle' | 'connecting' | 'streaming' | 'error';

interface UseMicSttStreamOptions {
  meetingId?: string;
}

const CHUNK_MS = 250;

function buildMicWsUrl(meetingId: string): string {
  // env 미지정 시 same-origin (useSubtitleWebSocket 과 동일 규칙)
  const base =
    process.env.NEXT_PUBLIC_STT_STREAM_WS_URL ||
    process.env.NEXT_PUBLIC_WS_URL ||
    (typeof window !== 'undefined'
      ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${process.env.NEXT_PUBLIC_BASE_PATH || ''}`
      : 'ws://localhost:8000');
  return `${base}/ws/stt/stream?meeting_id=${encodeURIComponent(meetingId)}`;
}

export function useMicSttStream({ meetingId }: UseMicSttStreamOptions) {
  const [status, setStatus] = useState<MicStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const seqRef = useRef(0);

  const stop = useCallback(() => {
    mediaRecorderRef.current?.stop();
    mediaRecorderRef.current = null;

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
      wsRef.current.close();
    }
    wsRef.current = null;
    setStatus('idle');
  }, []);

  const start = useCallback(async () => {
    if (!meetingId) return;
    if (status === 'streaming' || status === 'connecting') return;

    setStatus('connecting');
    setError(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000,
        },
        video: false,
      });

      streamRef.current = stream;
      const ws = new WebSocket(buildMicWsUrl(meetingId));
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'start', meeting_id: meetingId, codec: 'audio/webm' }));

        const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
        mediaRecorderRef.current = recorder;

        recorder.ondataavailable = async (event) => {
          if (!event.data || event.data.size === 0) return;
          if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

          const seq = seqRef.current++;
          const sentAt = Date.now();
          const buf = await event.data.arrayBuffer();

          wsRef.current.send(JSON.stringify({ type: 'audio_meta', seq, sent_at: sentAt, size: buf.byteLength }));
          wsRef.current.send(buf);
        };

        recorder.start(CHUNK_MS);
        setStatus('streaming');
      };

      ws.onerror = () => {
        setStatus('error');
        setError('마이크 스트리밍 WebSocket 연결 오류');
      };

      ws.onclose = () => {
        if (status !== 'idle') {
          setStatus('idle');
        }
      };
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : '마이크 스트리밍 시작 실패');
      stop();
    }
  }, [meetingId, status, stop]);

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return {
    status,
    error,
    start,
    stop,
    isStreaming: status === 'streaming',
  };
}

export default useMicSttStream;
