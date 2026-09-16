'use client';

/**
 * 위원회 위원 명단 모달 (2026-07-20)
 *
 * 실시간 방송 화면에서 현재 위원회의 위원 정보를 바로 확인한다.
 * 사진은 백엔드 압축 프록시(/api/councilors/{id}/photo, 128px JPEG)로
 * 저용량 제공. 데이터는 DB 명부(제12대 공식 명단) 기준.
 */

import React, { useEffect, useState } from 'react';

import { API_BASE_URL, getCouncilors } from '@/lib/api';
import type { CouncilorType } from '@/types';

interface CommitteeMembersModalProps {
  /** 위원회명 (채널명, 예: "기획재정위원회") */
  committee: string;
  /** ggc.go.kr 위원회 코드 (채널 code, 예: "C105") — 외부 링크용 */
  committeeCode?: string;
  isOpen: boolean;
  onClose: () => void;
}

function roleRank(role: string): number {
  if (role.includes('위원장') && !role.includes('부')) return 0;
  if (role.includes('부위원장')) return 1;
  return 2;
}

function partyClass(party: string): string {
  if (party.includes('국민의힘')) return 'text-red-600';
  if (party.includes('민주')) return 'text-blue-700';
  return 'text-gray-600';
}

/** 압축 프록시 사진 — 로드 실패 시 아이콘 폴백 (상태 기반, DOM 조작 없음) */
function MemberPhoto({ id, name }: { id: string; name: string }) {
  const [errored, setErrored] = useState(false);

  if (errored) {
    return (
      <div className="w-16 h-20 rounded bg-gray-100 mb-2 flex items-center justify-center text-2xl">
        👤
      </div>
    );
  }
  return (
    <img
      src={`${API_BASE_URL}/api/councilors/${id}/photo`}
      alt={name}
      loading="lazy"
      className="w-16 h-20 rounded object-cover bg-gray-100 mb-2"
      onError={() => setErrored(true)}
    />
  );
}

export default function CommitteeMembersModal({
  committee,
  committeeCode,
  isOpen,
  onClose,
}: CommitteeMembersModalProps) {
  const [members, setMembers] = useState<CouncilorType[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || members !== null) return;
    getCouncilors({ committee })
      .then((rows) => {
        const withRole = rows.map((c) => {
          const m = (c.committees || []).find((x) => x.name === committee);
          return { ...c, _role: m?.role || '위원' };
        });
        withRole.sort(
          (a, b) =>
            roleRank(a._role) - roleRank(b._role) ||
            a.name.localeCompare(b.name, 'ko'),
        );
        setMembers(withRole as CouncilorType[]);
      })
      .catch(() => setError('위원 명단을 불러오지 못했습니다.'));
  }, [isOpen, members, committee]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-label={`${committee} 위원 명단`}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] rounded-lg bg-white shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-5 py-3.5">
          <h2 className="text-base font-bold text-gray-900">
            👥 {committee} 위원 명단
            {members && (
              <span className="ml-2 text-sm font-normal text-gray-500">
                {members.length}명
              </span>
            )}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg"
            aria-label="닫기"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {error && <p className="text-sm text-red-600 py-6 text-center">{error}</p>}
          {!members && !error && (
            <p className="text-sm text-gray-400 py-8 text-center">
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-transparent align-middle mr-2" />
              불러오는 중…
            </p>
          )}
          {members && (
            <ul className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {members.map((c) => {
                const role = (c as CouncilorType & { _role?: string })._role || '위원';
                const isChair = role.includes('위원장');
                return (
                  <li
                    key={c.id}
                    className={`rounded-lg border p-3 flex flex-col items-center text-center ${
                      isChair ? 'border-brand/40 bg-brand/[0.03]' : 'border-gray-200'
                    }`}
                  >
                    <MemberPhoto id={c.id} name={c.name} />
                    <p className="text-sm font-bold text-gray-800">
                      {c.name}
                      <span
                        className={`ml-1 text-[11px] font-medium ${
                          isChair ? 'text-brand' : 'text-gray-500'
                        }`}
                      >
                        {role}
                      </span>
                    </p>
                    <p className={`text-[11px] font-medium ${partyClass(c.party || '')}`}>
                      {c.party}
                    </p>
                    <p className="text-[11px] text-gray-500">{c.district}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between border-t px-5 py-3 bg-gray-50 rounded-b-lg">
          <span className="text-[11px] text-gray-400">
            출처: 경기도의회 공식 명단 (제12대)
          </span>
          {committeeCode && (
            <a
              href={`https://www.ggc.go.kr/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode=${committeeCode}`}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-brand font-medium hover:underline"
            >
              의회 홈페이지에서 상세 보기 ↗
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
