'use client';

import React, { useCallback, useEffect, useState } from 'react';

import { Button, Card, Input, Select } from '@/components/ui';

import { apiClient } from '../../../lib/api';

interface DictionaryEntry {
  id: string;
  wrong_text: string;
  correct_text: string;
  category: string | null;
  created_by: string | null;
  created_at: string;
}

const CATEGORIES = [
  { value: '', label: '전체' },
  { value: 'councilor', label: '의원명' },
  { value: 'term', label: '의회용어' },
  { value: 'general', label: '일반' },
  { value: 'user_correction', label: '사용자 교정' },
];

export default function DictionaryPage() {
  const [entries, setEntries] = useState<DictionaryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState('');

  // 새 항목 추가 폼
  const [newWrong, setNewWrong] = useState('');
  const [newCorrect, setNewCorrect] = useState('');
  const [newCategory, setNewCategory] = useState('general');
  const [isAdding, setIsAdding] = useState(false);

  const loadEntries = useCallback(async () => {
    try {
      setIsLoading(true);
      const params = new URLSearchParams({ limit: '100', offset: '0' });
      if (categoryFilter) params.set('category', categoryFilter);

      const result = await apiClient<{ items: DictionaryEntry[]; total: number }>(
        `/api/dictionary?${params}`
      );
      setEntries(result.items || []);
      setTotal(result.total || 0);
    } catch {
      setEntries([]);
    } finally {
      setIsLoading(false);
    }
  }, [categoryFilter]);

  useEffect(() => {
    loadEntries();
  }, [loadEntries]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWrong.trim() || !newCorrect.trim()) return;

    try {
      setIsAdding(true);
      await apiClient('/api/dictionary', {
        method: 'POST',
        body: JSON.stringify({
          wrong_text: newWrong.trim(),
          correct_text: newCorrect.trim(),
          category: newCategory,
        }),
      });
      setNewWrong('');
      setNewCorrect('');
      await loadEntries();
    } catch {
      // 에러 무시
    } finally {
      setIsAdding(false);
    }
  };

  const handleDelete = async (entryId: string) => {
    try {
      await apiClient(`/api/dictionary/${entryId}`, { method: 'DELETE' });
      await loadEntries();
    } catch {
      // 에러 무시
    }
  };

  return (
    <div data-testid="dictionary-page" className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">용어사전 관리</h1>

      {/* 새 항목 추가 */}
      <form onSubmit={handleAdd} className="mb-6 p-4 bg-surface-raised rounded-lg border border-border">
        <h2 className="text-sm font-semibold mb-3">새 항목 추가</h2>
        <div className="flex gap-3 items-end flex-wrap">
          <div className="flex-1 min-w-[150px]">
            <Input
              label="잘못된 텍스트"
              type="text"
              value={newWrong}
              onChange={(e) => setNewWrong(e.target.value)}
              placeholder="예: 사내를 선포"
            />
          </div>
          <div className="flex-1 min-w-[150px]">
            <Input
              label="올바른 텍스트"
              type="text"
              value={newCorrect}
              onChange={(e) => setNewCorrect(e.target.value)}
              placeholder="예: 산회를 선포"
            />
          </div>
          <div className="w-32">
            <Select
              label="카테고리"
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
            >
              <option value="councilor">의원명</option>
              <option value="term">의회용어</option>
              <option value="general">일반</option>
            </Select>
          </div>
          <Button
            type="submit"
            loading={isAdding}
            disabled={!newWrong.trim() || !newCorrect.trim()}
          >
            {isAdding ? '추가 중...' : '추가'}
          </Button>
        </div>
      </form>

      {/* 카테고리 필터 */}
      <div className="flex gap-2 mb-4">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.value}
            onClick={() => setCategoryFilter(cat.value)}
            className={`px-3 py-1.5 text-sm rounded-pill transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              categoryFilter === cat.value
                ? 'bg-primary text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {cat.label}
          </button>
        ))}
        <span className="ml-auto text-sm text-text-dim self-center">{total}개 항목</span>
      </div>

      {/* 사전 테이블 */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <div className="text-center py-12 text-text-dim">
          사전 항목이 없습니다.
        </div>
      ) : (
        <Card padding="none" className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">잘못된 텍스트</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">올바른 텍스트</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">카테고리</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">등록자</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">작업</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {entries.map((entry) => (
                <tr key={entry.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-error font-mono">{entry.wrong_text}</td>
                  <td className="px-4 py-3 text-success font-mono">{entry.correct_text}</td>
                  <td className="px-4 py-3">
                    <span className="inline-block px-2 py-0.5 text-xs rounded-pill bg-gray-100 text-gray-600">
                      {CATEGORIES.find((c) => c.value === entry.category)?.label || entry.category || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-dim text-xs">{entry.created_by || '-'}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(entry.id)}
                      className="text-error hover:text-error/80 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                    >
                      삭제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
