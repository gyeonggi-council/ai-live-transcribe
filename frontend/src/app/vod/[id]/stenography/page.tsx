'use client';

import React, { useEffect, useState } from 'react';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Button, Card, Input, Modal, Textarea } from '@/components/ui';

import { useBreadcrumb } from '../../../../contexts/BreadcrumbContext';
import {
  apiClient,
  compareStenography,
  createStenographyRecord,
  deleteStenographyRecord,
  getStenographyRecords,
  updateStenographyRecord,
} from '../../../../lib/api';

import type {
  MeetingType,
  StenographyComparison,
  StenographyRecord,
} from '../../../../types';

interface StenographyPageProps {
  params: { id: string };
}

/**
 * 상태 배지
 */
function StatusBadge({ status }: { status: 'draft' | 'submitted' | 'approved' }) {
  const config = {
    draft: { label: '임시', color: 'bg-warning-bg/20 text-warning border-warning-bg/40' },
    submitted: { label: '제출됨', color: 'bg-primary-10 text-primary-dark border-primary-20' },
    approved: { label: '승인됨', color: 'bg-success/10 text-success border-success/30' },
  };

  const { label, color } = config[status];

  return (
    <span className={`px-2 py-1 text-xs font-medium rounded-md border ${color}`}>
      {label}
    </span>
  );
}

/**
 * 비교 결과 모달
 */
function ComparisonModal({
  comparison,
  onClose,
}: {
  comparison: StenographyComparison;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg max-w-6xl w-full mx-4 max-h-[90vh] flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">속기록-STT 자막 비교</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-2 gap-4">
            {/* 좌측: 속기록 */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">
                속기록 ({comparison.total_steno_lines}줄)
              </h3>
              <div className="space-y-2">
                {comparison.stenography_lines.map((line, i) => (
                  <div key={i} className="p-2 bg-gray-50 rounded text-sm text-gray-800">
                    {line}
                  </div>
                ))}
              </div>
            </div>
            {/* 우측: STT 자막 */}
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-3">
                STT 자막 ({comparison.total_subtitle_count}개)
              </h3>
              <div className="space-y-2">
                {comparison.subtitle_texts.map((text, i) => (
                  <div key={i} className="p-2 bg-primary-5 rounded text-sm text-gray-800">
                    {text}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-200">
          <Button variant="outline" onClick={onClose} className="w-full">
            닫기
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * 속기록 등록/수정 폼 모달
 */
function StenographyFormModal({
  meetingId,
  record,
  onClose,
  onSuccess,
}: {
  meetingId: string;
  record?: StenographyRecord;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [stenographerName, setStenographerName] = useState(record?.stenographer_name || '');
  const [content, setContent] = useState(record?.content || '');
  const [file, setFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // 폼이 초기값에서 변경되었는지 (ESC/오버레이 닫기로 입력 유실 방지)
  const isDirty =
    stenographerName !== (record?.stenographer_name || '') ||
    content !== (record?.content || '') ||
    file !== null;

  const handleClose = () => {
    if (isDirty && !window.confirm('작성 중인 내용이 사라집니다. 닫으시겠습니까?')) {
      return;
    }
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stenographerName.trim()) {
      alert('작성자명을 입력하세요.');
      return;
    }
    if (!content.trim() && !file) {
      alert('내용을 입력하거나 파일을 선택하세요.');
      return;
    }

    setIsSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('stenographer_name', stenographerName);
      if (content.trim()) {
        formData.append('content', content);
      }
      if (file) {
        formData.append('file', file);
      }

      if (record) {
        // 수정
        await updateStenographyRecord(meetingId, record.id, {
          stenographer_name: stenographerName,
          content: content || record.content,
        });
      } else {
        // 신규
        await createStenographyRecord(meetingId, formData);
      }
      onSuccess();
      onClose();
    } catch (err) {
      alert(err instanceof Error ? err.message : '등록/수정에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={handleClose}
      closeDisabled={isSubmitting}
      title={record ? '속기록 수정' : '속기록 등록'}
      size="lg"
      footer={
        <>
          <Button type="button" variant="outline" onClick={handleClose}>
            취소
          </Button>
          <Button
            data-testid="submit-button"
            type="button"
            onClick={handleSubmit}
            loading={isSubmitting}
          >
            {isSubmitting ? '처리 중...' : record ? '수정' : '등록'}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              작성자명 <span className="text-error">*</span>
            </label>
            <Input
              data-testid="stenographer-name-input"
              type="text"
              value={stenographerName}
              onChange={(e) => setStenographerName(e.target.value)}
              placeholder="예: 홍길동"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              내용 {!record && <span className="text-xs text-gray-500">(또는 파일 선택)</span>}
            </label>
            <Textarea
              data-testid="content-input"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={10}
              className="resize-none"
              placeholder="속기록 내용을 입력하세요..."
            />
          </div>
          {!record && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                파일 업로드 (.txt, .doc, .docx)
              </label>
              <Input
                data-testid="file-input"
                type="file"
                accept=".txt,.doc,.docx"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </div>
          )}
        </div>
      </form>
    </Modal>
  );
}

export default function StenographyPage({ params }: StenographyPageProps) {
  const router = useRouter();
  const { setTitle } = useBreadcrumb();
  const { id } = params;

  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [records, setRecords] = useState<StenographyRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const [showFormModal, setShowFormModal] = useState(false);
  const [editingRecord, setEditingRecord] = useState<StenographyRecord | undefined>();
  const [comparisonData, setComparisonData] = useState<StenographyComparison | null>(null);

  // 초기 데이터 로드
  useEffect(() => {
    async function fetchData() {
      try {
        setIsLoading(true);
        setError(null);

        const [meetingData, recordsData] = await Promise.all([
          apiClient<MeetingType>(`/api/meetings/${id}`),
          getStenographyRecords(id),
        ]);

        setMeeting(meetingData);
        setTitle(meetingData.title);
        setRecords(recordsData);
      } catch (err) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();
  }, [id, setTitle]);

  // 속기록 삭제
  const handleDelete = async (recordId: string) => {
    if (!window.confirm('속기록을 삭제하시겠습니까?')) return;

    try {
      await deleteStenographyRecord(id, recordId);
      setRecords((prev) => prev.filter((r) => r.id !== recordId));
    } catch (err) {
      alert(err instanceof Error ? err.message : '삭제에 실패했습니다.');
    }
  };

  // 상태 변경
  const handleStatusChange = async (recordId: string, newStatus: 'draft' | 'submitted' | 'approved') => {
    try {
      const updated = await updateStenographyRecord(id, recordId, { status: newStatus });
      setRecords((prev) => prev.map((r) => (r.id === recordId ? updated : r)));
    } catch (err) {
      alert(err instanceof Error ? err.message : '상태 변경에 실패했습니다.');
    }
  };

  // 비교 실행
  const handleCompare = async (recordId: string) => {
    try {
      const data = await compareStenography(id, recordId);
      setComparisonData(data);
    } catch (err) {
      alert(err instanceof Error ? err.message : '비교에 실패했습니다.');
    }
  };

  // 등록/수정 성공 시
  const handleFormSuccess = () => {
    getStenographyRecords(id).then(setRecords).catch(console.error);
  };

  // 로딩
  if (isLoading) {
    return (
      <div data-testid="page-loading" className="min-h-screen flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  // 에러
  if (error || !meeting) {
    return (
      <div data-testid="page-error" className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-error mb-4">오류가 발생했습니다.</p>
          <Button onClick={() => router.push('/')}>홈으로 이동</Button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="stenography-page" className="flex flex-col h-full">
      {/* 상단 툴바 */}
      <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/vod/${id}`}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            돌아가기
          </Link>
          <h1 className="text-lg font-semibold text-gray-900">속기록 관리</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            data-testid="add-record-button"
            onClick={() => {
              setEditingRecord(undefined);
              setShowFormModal(true);
            }}
          >
            속기록 등록
          </Button>
        </div>
      </div>

      {/* 메인 콘텐츠 */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* 회의 정보 */}
        <Card className="mb-4">
          <h2 className="text-base font-semibold text-gray-900 mb-2">{meeting.title}</h2>
          <div className="flex gap-4 text-sm text-gray-500">
            <span>일시: {meeting.meeting_date}</span>
            {meeting.committee && <span>위원회: {meeting.committee}</span>}
          </div>
        </Card>

        {/* 속기록 목록 */}
        <Card data-testid="stenography-list" padding="none">
          {records.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              등록된 속기록이 없습니다.
            </div>
          ) : (
            <div className="divide-y divide-gray-200">
              {records.map((record) => (
                <div key={record.id} className="p-4">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">{record.stenographer_name}</span>
                      <StatusBadge status={record.status} />
                    </div>
                    <div className="flex items-center gap-2">
                      {/* 상태 변경 드롭다운 */}
                      <select
                        data-testid={`status-select-${record.id}`}
                        value={record.status}
                        onChange={(e) => handleStatusChange(record.id, e.target.value as 'draft' | 'submitted' | 'approved')}
                        className="px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary"
                      >
                        <option value="draft">임시</option>
                        <option value="submitted">제출됨</option>
                        <option value="approved">승인됨</option>
                      </select>
                      <Link
                        href={`/vod/${id}/stenography/${record.id}/edit`}
                        className="px-3 py-1 text-xs bg-primary text-white rounded hover:bg-primary-dark transition-colors"
                        data-testid={`edit-button-${record.id}`}
                      >
                        편집
                      </Link>
                      <button
                        data-testid={`compare-button-${record.id}`}
                        onClick={() => handleCompare(record.id)}
                        className="px-3 py-1 text-xs bg-primary text-white rounded hover:bg-primary-dark transition-colors"
                      >
                        비교
                      </button>
                      <button
                        onClick={() => {
                          setEditingRecord(record);
                          setShowFormModal(true);
                        }}
                        className="px-3 py-1 text-xs bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors"
                      >
                        수정
                      </button>
                      <button
                        onClick={() => handleDelete(record.id)}
                        className="px-3 py-1 text-xs bg-error text-white rounded hover:bg-error/90 transition-colors"
                      >
                        삭제
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 mb-2">
                    작성일: {new Date(record.created_at).toLocaleDateString()}
                    {record.filename && ` · 파일: ${record.filename}`}
                  </p>
                  <div className="bg-gray-50 p-3 rounded text-sm text-gray-800 whitespace-pre-wrap max-h-32 overflow-y-auto">
                    {record.content}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* 폼 모달 */}
      {showFormModal && (
        <StenographyFormModal
          meetingId={id}
          record={editingRecord}
          onClose={() => {
            setShowFormModal(false);
            setEditingRecord(undefined);
          }}
          onSuccess={handleFormSuccess}
        />
      )}

      {/* 비교 모달 */}
      {comparisonData && (
        <ComparisonModal
          comparison={comparisonData}
          onClose={() => setComparisonData(null)}
        />
      )}
    </div>
  );
}
