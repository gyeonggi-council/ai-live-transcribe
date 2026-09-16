'use client';

import React, { useState } from 'react';

import { updateTranscriptStatus } from '../lib/api';

interface TranscriptStatusBadgeProps {
  meetingId: string;
  status: 'draft' | 'reviewing' | 'final';
  onStatusChange?: (newStatus: 'draft' | 'reviewing' | 'final') => void;
  editable?: boolean;
}

const STATUS_CONFIG = {
  draft: {
    label: '임시',
    bgColor: 'bg-gray-100',
    textColor: 'text-gray-700',
    dotColor: 'bg-gray-400',
  },
  reviewing: {
    label: '검토중',
    bgColor: 'bg-warning-bg/10',
    textColor: 'text-warning',
    dotColor: 'bg-warning-bg',
  },
  final: {
    label: '확정',
    bgColor: 'bg-success/10',
    textColor: 'text-success',
    dotColor: 'bg-success',
  },
};

const STATUS_TRANSITIONS: Record<string, Array<'draft' | 'reviewing' | 'final'>> = {
  draft: ['reviewing'],
  reviewing: ['draft', 'final'],
  final: ['reviewing'],
};

export default function TranscriptStatusBadge({
  meetingId,
  status,
  onStatusChange,
  editable = false,
}: TranscriptStatusBadgeProps) {
  const [showMenu, setShowMenu] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.draft;

  const handleStatusChange = async (newStatus: 'draft' | 'reviewing' | 'final') => {
    try {
      setIsUpdating(true);
      await updateTranscriptStatus(meetingId, newStatus);
      onStatusChange?.(newStatus);
      setShowMenu(false);
    } catch {
      alert('상태 변경에 실패했습니다.');
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <div className="relative inline-block" data-testid="transcript-status-badge">
      <button
        onClick={() => editable && setShowMenu(!showMenu)}
        disabled={isUpdating}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.bgColor} ${config.textColor} ${
          editable ? 'cursor-pointer hover:ring-2 hover:ring-primary/30' : 'cursor-default'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${config.dotColor}`} />
        {isUpdating ? '변경중...' : config.label}
        {editable && (
          <svg className="w-3 h-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>

      {showMenu && editable && (
        <div className="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-md shadow-lg z-10 py-1 min-w-[120px]">
          {STATUS_TRANSITIONS[status]?.map((nextStatus) => {
            const nextConfig = STATUS_CONFIG[nextStatus];
            return (
              <button
                key={nextStatus}
                onClick={() => handleStatusChange(nextStatus)}
                className="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 flex items-center gap-2"
              >
                <span className={`w-2 h-2 rounded-full ${nextConfig.dotColor}`} />
                {nextConfig.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
