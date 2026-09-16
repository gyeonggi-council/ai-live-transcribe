'use client';

import React, { useCallback, useEffect, useState } from 'react';

import {
  addAgenda,
  addParticipant,
  deleteAgenda,
  getAgendas,
  getParticipants,
  removeParticipant,
  updateMeeting,
} from '../lib/api';
import Button from './ui/Button';
import Card from './ui/Card';
import Input from './ui/Input';
import Select from './ui/Select';

import type { MeetingUpdateData } from '../lib/api';
import type { AgendaType, MeetingType, ParticipantType } from '../types';

interface MeetingInfoPanelProps {
  meeting: MeetingType;
  onMeetingUpdate?: (updated: MeetingType) => void;
}

const MEETING_TYPE_OPTIONS = [
  '본회의',
  '상임위원회',
  '특별위원회',
  '예산결산특별위원회',
  '기타',
];

export default function MeetingInfoPanel({
  meeting,
  onMeetingUpdate,
}: MeetingInfoPanelProps) {
  const [participants, setParticipants] = useState<ParticipantType[]>([]);
  const [agendas, setAgendas] = useState<AgendaType[]>([]);
  const [isEditing, setIsEditing] = useState(false);

  // 편집 폼 상태
  const [editMeetingType, setEditMeetingType] = useState(meeting.meeting_type || '');
  const [editCommittee, setEditCommittee] = useState(meeting.committee || '');

  // 참석자 추가 폼
  const [newParticipantName, setNewParticipantName] = useState('');
  const [newParticipantRole, setNewParticipantRole] = useState('');

  // 안건 추가 폼
  const [newAgendaTitle, setNewAgendaTitle] = useState('');

  const loadData = useCallback(async () => {
    try {
      const [p, a] = await Promise.all([
        getParticipants(meeting.id),
        getAgendas(meeting.id),
      ]);
      setParticipants(p);
      setAgendas(a);
    } catch {
      // 데이터 로드 실패 무시 (테이블 미존재 등)
    }
  }, [meeting.id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSaveMeetingInfo = async () => {
    const data: MeetingUpdateData = {};
    if (editMeetingType !== (meeting.meeting_type || '')) {
      data.meeting_type = editMeetingType;
    }
    if (editCommittee !== (meeting.committee || '')) {
      data.committee = editCommittee;
    }

    if (Object.keys(data).length === 0) {
      setIsEditing(false);
      return;
    }

    try {
      await updateMeeting(meeting.id, data);
      onMeetingUpdate?.({
        ...meeting,
        meeting_type: editMeetingType || null,
        committee: editCommittee || null,
      });
      setIsEditing(false);
    } catch {
      alert('회의 정보 수정에 실패했습니다.');
    }
  };

  const handleAddParticipant = async () => {
    if (!newParticipantName.trim()) return;

    try {
      const participant = await addParticipant(meeting.id, {
        councilor_id: `c_${Date.now()}`,
        name: newParticipantName.trim(),
        role: newParticipantRole.trim() || undefined,
      });
      setParticipants((prev) => [...prev, participant]);
      setNewParticipantName('');
      setNewParticipantRole('');
    } catch {
      alert('참석자 추가에 실패했습니다.');
    }
  };

  const handleRemoveParticipant = async (participantId: string) => {
    try {
      await removeParticipant(meeting.id, participantId);
      setParticipants((prev) => prev.filter((p) => p.id !== participantId));
    } catch {
      alert('참석자 제거에 실패했습니다.');
    }
  };

  const handleAddAgenda = async () => {
    if (!newAgendaTitle.trim()) return;

    try {
      const agenda = await addAgenda(meeting.id, {
        order_num: agendas.length + 1,
        title: newAgendaTitle.trim(),
      });
      setAgendas((prev) => [...prev, agenda]);
      setNewAgendaTitle('');
    } catch {
      alert('안건 추가에 실패했습니다.');
    }
  };

  const handleDeleteAgenda = async (agendaId: string) => {
    try {
      await deleteAgenda(meeting.id, agendaId);
      setAgendas((prev) => prev.filter((a) => a.id !== agendaId));
    } catch {
      alert('안건 삭제에 실패했습니다.');
    }
  };

  return (
    <Card data-testid="meeting-info-panel" padding="md">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-900">회의 정보</h3>
        <button
          onClick={() => setIsEditing(!isEditing)}
          className="text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
        >
          {isEditing ? '취소' : '편집'}
        </button>
      </div>

      {/* 회의 유형 / 위원회 */}
      {isEditing ? (
        <div className="space-y-2 mb-4">
          <Select
            label="회의 유형"
            value={editMeetingType}
            onChange={(e) => setEditMeetingType(e.target.value)}
          >
            <option value="">선택</option>
            {MEETING_TYPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </Select>
          <Input
            label="위원회"
            type="text"
            value={editCommittee}
            onChange={(e) => setEditCommittee(e.target.value)}
            placeholder="예: 교육기획위원회"
          />
          <Button onClick={handleSaveMeetingInfo} size="sm" className="w-full">
            저장
          </Button>
        </div>
      ) : (
        <div className="space-y-1 mb-4 text-sm text-gray-700">
          <div className="flex justify-between">
            <span className="text-gray-500">유형:</span>
            <span>{meeting.meeting_type || '-'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">위원회:</span>
            <span>{meeting.committee || '-'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">날짜:</span>
            <span>{meeting.meeting_date}</span>
          </div>
        </div>
      )}

      {/* 참석자 목록 */}
      <div className="border-t border-gray-100 pt-3 mb-3">
        <h4 className="text-xs font-medium text-gray-600 mb-2">
          참석자 ({participants.length})
        </h4>

        {participants.length > 0 && (
          <div className="space-y-1 mb-2">
            {participants.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between text-sm bg-gray-50 px-2 py-1 rounded"
              >
                <span>
                  {p.name}
                  {p.role && (
                    <span className="text-xs text-gray-500 ml-1">({p.role})</span>
                  )}
                </span>
                <button
                  onClick={() => handleRemoveParticipant(p.id)}
                  className="text-error hover:text-error/80 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                >
                  삭제
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-1">
          <input
            type="text"
            value={newParticipantName}
            onChange={(e) => setNewParticipantName(e.target.value)}
            placeholder="이름"
            className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded-md focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <input
            type="text"
            value={newParticipantRole}
            onChange={(e) => setNewParticipantRole(e.target.value)}
            placeholder="역할"
            className="w-20 px-2 py-1 text-xs border border-gray-300 rounded-md focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <button
            onClick={handleAddParticipant}
            disabled={!newParticipantName.trim()}
            className="px-2 py-1 text-xs bg-primary text-white rounded-md hover:bg-primary-dark disabled:bg-gray-300 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            추가
          </button>
        </div>
      </div>

      {/* 안건 목록 */}
      <div className="border-t border-gray-100 pt-3">
        <h4 className="text-xs font-medium text-gray-600 mb-2">
          안건 ({agendas.length})
        </h4>

        {agendas.length > 0 && (
          <div className="space-y-1 mb-2">
            {agendas.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between text-sm bg-gray-50 px-2 py-1 rounded"
              >
                <span className="truncate flex-1">
                  <span className="text-xs text-gray-400 mr-1">#{a.order_num}</span>
                  {a.title}
                </span>
                <button
                  onClick={() => handleDeleteAgenda(a.id)}
                  className="text-error hover:text-error/80 text-xs ml-1 shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                >
                  삭제
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-1">
          <input
            type="text"
            value={newAgendaTitle}
            onChange={(e) => setNewAgendaTitle(e.target.value)}
            placeholder="안건 제목"
            className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded-md focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
            onKeyDown={(e) => e.key === 'Enter' && handleAddAgenda()}
          />
          <button
            onClick={handleAddAgenda}
            disabled={!newAgendaTitle.trim()}
            className="px-2 py-1 text-xs bg-primary text-white rounded-md hover:bg-primary-dark disabled:bg-gray-300 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            추가
          </button>
        </div>
      </div>
    </Card>
  );
}
