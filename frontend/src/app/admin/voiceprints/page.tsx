'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { Callout } from '@/components/ui';

import { getCouncilors, getVoiceprints, enrollVoiceprint, deleteVoiceprint, setVoiceprintChair } from '../../../lib/api';

import type { CouncilorType } from '../../../types';

interface EnrolledInfo {
  duration_ms: number | null;
  committee: string | null;
  source: string;
  is_chair: boolean;
}

const MAX_PER_COMMITTEE = 4;

export default function VoiceprintsPage() {
  const [councilors, setCouncilors] = useState<CouncilorType[]>([]);
  const [enrolled, setEnrolled] = useState<Record<string, EnrolledInfo>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [committeeFilter, setCommitteeFilter] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [cs, vp] = await Promise.all([getCouncilors(), getVoiceprints()]);
      setCouncilors(cs);
      const map: Record<string, EnrolledInfo> = {};
      for (const v of vp.voiceprints) {
        map[v.councilor_id] = { duration_ms: v.duration_ms, committee: v.committee, source: v.source, is_chair: !!v.is_chair };
      }
      setEnrolled(map);
    } catch (e) {
      setMessage({ kind: 'err', text: e instanceof Error ? e.message : '불러오기 실패' });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const committees = useMemo(() => {
    const set = new Set<string>();
    councilors.forEach((c) => c.committee && set.add(c.committee));
    return Array.from(set).sort();
  }, [councilors]);

  // 위원회별 등록 인원 수 (4명 한도 경고용)
  const enrolledCountByCommittee = useMemo(() => {
    const counts: Record<string, number> = {};
    Object.values(enrolled).forEach((e) => {
      if (e.committee) counts[e.committee] = (counts[e.committee] || 0) + 1;
    });
    return counts;
  }, [enrolled]);

  // 위원회별 지정된 위원장 (councilor_id)
  const chairByCommittee = useMemo(() => {
    const m: Record<string, string> = {};
    Object.entries(enrolled).forEach(([cid, e]) => {
      if (e.is_chair && e.committee) m[e.committee] = cid;
    });
    return m;
  }, [enrolled]);

  const filtered = useMemo(
    () => (committeeFilter ? councilors.filter((c) => c.committee === committeeFilter) : councilors),
    [councilors, committeeFilter]
  );

  const handleEnroll = async (councilorId: string, file: File) => {
    setBusyId(councilorId);
    setMessage(null);
    try {
      const r = await enrollVoiceprint(councilorId, file);
      setMessage({ kind: 'ok', text: `${r.councilor_name} 등록 완료 (${Math.round((r.duration_ms || 0) / 100) / 10}초)` });
      await load();
    } catch (e) {
      setMessage({ kind: 'err', text: e instanceof Error ? e.message : '등록 실패' });
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (councilorId: string) => {
    setBusyId(councilorId);
    try {
      await deleteVoiceprint(councilorId);
      await load();
    } catch (e) {
      setMessage({ kind: 'err', text: e instanceof Error ? e.message : '삭제 실패' });
    } finally {
      setBusyId(null);
    }
  };

  const handleSetChair = async (councilorId: string, isChair: boolean) => {
    setBusyId(councilorId);
    try {
      await setVoiceprintChair(councilorId, isChair);
      await load();
    } catch (e) {
      setMessage({ kind: 'err', text: e instanceof Error ? e.message : '위원장 지정 실패' });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-xl font-bold mb-1">의원 목소리 등록 (실명 화자 식별)</h1>
      <p className="text-sm text-gray-500 mb-4">
        의원 음성 샘플(2~10초)을 등록하면 실시간 자막의 화자가 &quot;화자 1/2&quot; 대신 실제 의원 이름으로 표시됩니다.
        OpenAI 제약상 <b>위원회당 최대 {MAX_PER_COMMITTEE}명</b>까지 인식되므로, 위원장 등 발언이 많은 의원을 우선 등록하세요.
      </p>

      {message && (
        <Callout variant={message.kind === 'ok' ? 'success' : 'danger'} className="mb-3">
          {message.text}
        </Callout>
      )}

      <div className="mb-4 flex items-center gap-2">
        <label className="text-sm text-gray-600">위원회</label>
        <select
          className="border border-gray-300 rounded-md bg-white px-2 py-1 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
          value={committeeFilter}
          onChange={(e) => setCommitteeFilter(e.target.value)}
        >
          <option value="">전체</option>
          {committees.map((c) => (
            <option key={c} value={c}>
              {c} ({enrolledCountByCommittee[c] || 0}명 등록)
            </option>
          ))}
        </select>
        {committeeFilter && (enrolledCountByCommittee[committeeFilter] || 0) > MAX_PER_COMMITTEE && (
          <span className="text-xs text-warning">
            ⚠ {committeeFilter}에 {enrolledCountByCommittee[committeeFilter]}명 등록됨 — 동시 인식은 {MAX_PER_COMMITTEE}명(위원장+현재 위원). 회의 중 자동 교체됩니다.
          </span>
        )}
        {committeeFilter && !chairByCommittee[committeeFilter] && (
          <span className="text-xs text-error">⚠ {committeeFilter} 위원장 미지정 — 실시간 식별 정확도가 떨어집니다.</span>
        )}
      </div>

      {isLoading ? (
        <p className="text-gray-400">불러오는 중…</p>
      ) : (
        <table className="w-full text-sm border-t">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="py-2">의원</th>
              <th>위원회</th>
              <th>상태</th>
              <th>위원장</th>
              <th className="text-right">목소리 샘플</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => {
              const e = enrolled[c.id];
              const busy = busyId === c.id;
              return (
                <tr key={c.id} className="border-b hover:bg-gray-50">
                  <td className="py-2">
                    <span className="font-medium">{c.name}</span>
                    {c.party && <span className="ml-2 text-xs text-gray-400">{c.party}</span>}
                  </td>
                  <td className="text-gray-600">{c.committee || '-'}</td>
                  <td>
                    {e ? (
                      <span className="inline-block px-2 py-0.5 rounded bg-primary-5 text-primary text-xs">
                        등록됨 {e.duration_ms ? `· ${Math.round(e.duration_ms / 100) / 10}초` : ''}
                      </span>
                    ) : (
                      <span className="text-gray-400 text-xs">미등록</span>
                    )}
                  </td>
                  <td>
                    <button
                      className={`text-xs px-2 py-1 border rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-40 ${e?.is_chair ? 'bg-primary text-white border-primary' : 'border-gray-300 bg-white hover:bg-gray-50'}`}
                      disabled={!e || busy}
                      title={e ? '위원회당 1명, 회의 내내 발언하는 위원장' : '먼저 목소리를 등록하세요'}
                      onClick={() => handleSetChair(c.id, !e?.is_chair)}
                    >
                      {e?.is_chair ? '위원장 ✓' : '위원장 지정'}
                    </button>
                  </td>
                  <td className="text-right">
                    <div className="inline-flex items-center gap-2">
                      <label className={`cursor-pointer text-xs px-2 py-1 border border-gray-300 rounded-md bg-white transition-colors ${busy ? 'opacity-50' : 'hover:bg-gray-50'}`}>
                        {e ? '교체' : '등록'}
                        <input
                          type="file"
                          accept="audio/*,video/*"
                          className="hidden"
                          disabled={busy}
                          onChange={(ev) => {
                            const f = ev.target.files?.[0];
                            if (f) handleEnroll(c.id, f);
                            ev.target.value = '';
                          }}
                        />
                      </label>
                      {e && (
                        <button
                          className="text-xs px-2 py-1 border border-error/30 rounded-md bg-white text-error transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary hover:bg-error/5 disabled:opacity-50"
                          disabled={busy}
                          onClick={() => handleDelete(c.id)}
                        >
                          삭제
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
