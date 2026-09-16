'use client';

import { useCallback, useEffect, useState } from 'react';

import { Button, Input, Select } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient } from '@/lib/api';

interface UserItem {
  id: string;
  username: string;
  display_name: string;
  role: string;
  assigned_committee: string | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

const ROLES = [
  { value: 'admin', label: '관리자' },
  { value: 'stenographer', label: '속기사' },
  { value: 'committee_staff', label: '위원회 직원' },
  { value: 'meeting_manager', label: '회의 관리자' },
  { value: 'staff', label: '일반 직원' },
];

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-error/10 text-error',
  stenographer: 'bg-primary-5 text-primary-dark',
  committee_staff: 'bg-info/10 text-info',
  meeting_manager: 'bg-success/10 text-success',
  staff: 'bg-surface-raised text-text-secondary',
};

export default function AdminUsersPage() {
  const { user: currentUser, loading: authLoading } = useAuth();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 새 사용자 폼
  const [showForm, setShowForm] = useState(false);
  // 비밀번호 칸은 없다 — 이 서비스는 아이디·비밀번호로 로그인하지 않는다(2026-08-28).
  // 아이디(username)는 여전히 필요하다. 의정포털 usercode 와 맞춰야 QR 로그인이
  // 이 계정을 찾는다 — 여기서 만드는 것은 '자격증명'이 아니라 '권한을 미리 얹은 자리'다.
  const [formData, setFormData] = useState({
    username: '', display_name: '', role: 'staff', assigned_committee: '',
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [formLoading, setFormLoading] = useState(false);

  // 편집 모드
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editData, setEditData] = useState<Partial<UserItem>>({});

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient<UserItem[]>('/api/admin/users');
      setUsers(data);
    } catch {
      setError('사용자 목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormLoading(true);
    setFormError(null);
    try {
      await apiClient('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          ...formData,
          assigned_committee: formData.assigned_committee || null,
        }),
      });
      setShowForm(false);
      setFormData({ username: '', display_name: '', role: 'staff', assigned_committee: '' });
      loadUsers();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '생성 실패');
    } finally {
      setFormLoading(false);
    }
  };

  const handleUpdate = async (userId: string) => {
    try {
      await apiClient(`/api/admin/users/${userId}`, {
        method: 'PATCH',
        body: JSON.stringify(editData),
      });
      setEditingId(null);
      setEditData({});
      loadUsers();
    } catch (err) {
      alert(err instanceof Error ? err.message : '수정 실패');
    }
  };

  const handleDelete = async (userId: string, username: string) => {
    if (!confirm(`"${username}" 사용자를 삭제하시겠습니까?`)) return;
    try {
      await apiClient(`/api/admin/users/${userId}`, { method: 'DELETE' });
      loadUsers();
    } catch (err) {
      alert(err instanceof Error ? err.message : '삭제 실패');
    }
  };

  const handleToggleActive = async (userId: string, currentActive: boolean) => {
    try {
      await apiClient(`/api/admin/users/${userId}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !currentActive }),
      });
      loadUsers();
    } catch (err) {
      alert(err instanceof Error ? err.message : '상태 변경 실패');
    }
  };

  if (authLoading) {
    return <div className="p-8 text-center text-text-muted">로딩 중...</div>;
  }

  if (!currentUser || currentUser.role !== 'admin') {
    return <div className="p-8 text-center text-text-muted">관리자 권한이 필요합니다.</div>;
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-text">사용자 관리</h1>
          <p className="text-sm text-text-muted mt-0.5">{users.length}명의 사용자</p>
        </div>
        <Button variant="primary" size="md" onClick={() => setShowForm(!showForm)}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          사용자 추가
        </Button>
      </div>

      {/* 새 사용자 폼 */}
      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 p-4 bg-surface border border-border rounded-lg space-y-3">
          <h3 className="text-sm font-bold text-text-secondary">새 사용자 등록</h3>
          {formError && <p className="text-sm text-error">{formError}</p>}
          <div className="grid grid-cols-2 gap-3">
            <Input
              placeholder="아이디"
              value={formData.username}
              onChange={(e) => setFormData(d => ({ ...d, username: e.target.value }))}
              required
            />
            <Input
              placeholder="표시 이름"
              value={formData.display_name}
              onChange={(e) => setFormData(d => ({ ...d, display_name: e.target.value }))}
              required
            />
            <Select
              value={formData.role}
              onChange={(e) => setFormData(d => ({ ...d, role: e.target.value }))}
            >
              {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </Select>
          </div>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" size="md" disabled={formLoading}>
              {formLoading ? '생성 중...' : '생성'}
            </Button>
            <Button variant="outline" size="md" onClick={() => setShowForm(false)}>
              취소
            </Button>
          </div>
        </form>
      )}

      {/* 에러/로딩 */}
      {error && <p className="text-error text-sm mb-4">{error}</p>}
      {loading ? (
        <div className="text-center py-8 text-text-muted">로딩 중...</div>
      ) : (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-raised border-b border-border">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-text-secondary">사용자</th>
                <th className="text-left px-4 py-3 font-medium text-text-secondary">역할</th>
                <th className="text-left px-4 py-3 font-medium text-text-secondary">상태</th>
                <th className="text-left px-4 py-3 font-medium text-text-secondary">마지막 로그인</th>
                <th className="text-right px-4 py-3 font-medium text-text-secondary">작업</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-surface-raised/50">
                  <td className="px-4 py-3">
                    {editingId === u.id ? (
                      <input
                        value={editData.display_name ?? u.display_name}
                        onChange={(e) => setEditData(d => ({ ...d, display_name: e.target.value }))}
                        className="px-2 py-1 border border-border bg-surface-raised text-text rounded text-sm w-full"
                      />
                    ) : (
                      <div>
                        <div className="font-medium text-text">{u.display_name}</div>
                        <div className="text-xs text-text-muted">{u.username}</div>
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {editingId === u.id ? (
                      <select
                        value={editData.role ?? u.role}
                        onChange={(e) => setEditData(d => ({ ...d, role: e.target.value }))}
                        className="px-2 py-1 border border-border bg-surface-raised text-text rounded text-sm"
                      >
                        {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </select>
                    ) : (
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_COLORS[u.role] || 'bg-surface-raised'}`}>
                        {ROLES.find(r => r.value === u.role)?.label || u.role}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggleActive(u.id, u.is_active)}
                      className={`px-2 py-0.5 rounded-full text-xs font-medium cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                        u.is_active ? 'bg-success/10 text-success' : 'bg-error/10 text-error'
                      }`}
                    >
                      {u.is_active ? '활성' : '비활성'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-xs text-text-muted">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString('ko-KR') : '-'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {editingId === u.id ? (
                      <div className="flex gap-1 justify-end">
                        <button onClick={() => handleUpdate(u.id)} className="px-2 py-1 bg-primary text-white rounded text-xs hover:bg-primary-dark transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">저장</button>
                        <button onClick={() => { setEditingId(null); setEditData({}); }} className="px-2 py-1 border border-border text-text rounded text-xs">취소</button>
                      </div>
                    ) : (
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => { setEditingId(u.id); setEditData({}); }}
                          className="px-2 py-1 text-xs text-text-secondary hover:text-primary border border-border rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          편집
                        </button>
                        {u.id !== currentUser?.id && (
                          <button
                            onClick={() => handleDelete(u.id, u.username)}
                            className="px-2 py-1 text-xs text-error hover:text-error/70 border border-error/30 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                          >
                            삭제
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
