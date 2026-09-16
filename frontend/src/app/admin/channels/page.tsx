'use client';

/**
 * 채널 관리 — 다른 의회가 자기 생중계 주소를 넣는 화면 (2026-09-16)
 *
 * 흐름은 셋이다.
 *   ① 의회 고르기(48곳) → 생중계 페이지 주소가 자동으로 채워진다
 *   ② [채널 자동 찾기] → 후보를 확인하고 저장
 *   ③ 못 찾으면 영상 주소(.m3u8)를 직접 입력
 *
 * ③을 항상 남겨 두는 이유: 대부분의 의회는 **방송 중일 때만** 영상 주소가 드러난다
 * (서울·대구·충남·고양·성남에서 실측). 자동 찾기는 편의지 전제가 아니다.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import RoleGuard from '@/components/RoleGuard';
import { Button, Callout, Input, Select } from '@/components/ui';
import {
  createAdminChannel,
  createAdminChannelsBulk,
  deleteAdminChannel,
  discoverChannels,
  listAdminChannels,
  listCouncilPresets,
  probeAdminChannel,
  updateAdminChannel,
  type AdminChannel,
  type CouncilPreset,
  type DiscoveryResult,
} from '@/lib/api';

const PROVIDERS = [
  { value: 'probe', label: '영상 주소로 자동 판정 (권장)' },
  { value: 'ggc', label: '기관 생중계 API' },
  { value: 'manual', label: '관리자가 직접 켜고 끔' },
  { value: 'none', label: '판정하지 않음' },
];

const PROVIDER_LABEL: Record<string, string> = Object.fromEntries(
  PROVIDERS.map((p) => [p.value, p.label]),
);

function ChannelAdmin() {
  const [items, setItems] = useState<AdminChannel[]>([]);
  const [presets, setPresets] = useState<CouncilPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [pageUrl, setPageUrl] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [picked, setPicked] = useState<Record<string, boolean>>({});

  const [manual, setManual] = useState({ id: '', name: '', stream_url: '' });
  const [probing, setProbing] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAdminChannels();
      setItems(res.items ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    listCouncilPresets()
      .then((res) => setPresets(res.councils ?? []))
      .catch(() => setPresets([]));
  }, [load]);

  const presetGroups = useMemo(() => {
    const wide = presets.filter((p) => p.region === '광역');
    const local = presets.filter((p) => p.region !== '광역');
    return { wide, local };
  }, [presets]);

  const handleDiscover = async () => {
    if (!pageUrl.trim()) return;
    setDiscovering(true);
    setDiscovery(null);
    setError(null);
    try {
      const res = await discoverChannels(pageUrl.trim());
      setDiscovery(res);
      // 재생목록이 확인된 후보만 기본 선택 — 나머지는 사람이 판단한다
      setPicked(
        Object.fromEntries(res.candidates.map((c) => [c.suggested_id, c.verified === true])),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDiscovering(false);
    }
  };

  const handleSaveDiscovered = async () => {
    if (!discovery) return;
    const chosen = discovery.candidates.filter((c) => picked[c.suggested_id]);
    if (chosen.length === 0) return;
    try {
      const res = await createAdminChannelsBulk(
        chosen.map((c) => ({
          id: c.suggested_id,
          name: c.name || c.suggested_id,
          stream_url: c.m3u8_url,
          page_url: discovery.page_url,
          status_provider: 'probe',
        })),
      );
      setNotice(
        `${res.created.length}개를 등록했습니다.` +
          (res.skipped.length ? ` (이미 있는 ${res.skipped.length}개는 건너뜀)` : '') +
          (res.errors.length ? ` 실패 ${res.errors.length}개: ${res.errors[0].detail}` : ''),
      );
      setDiscovery(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleManualAdd = async () => {
    if (!manual.id.trim() || !manual.name.trim() || !manual.stream_url.trim()) return;
    try {
      await createAdminChannel({ ...manual, status_provider: 'probe' });
      setManual({ id: '', name: '', stream_url: '' });
      setNotice('채널을 등록했습니다.');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleToggleActive = async (ch: AdminChannel) => {
    await updateAdminChannel(ch.id, { is_active: !ch.is_active });
    await load();
  };

  const handleProvider = async (ch: AdminChannel, value: string) => {
    await updateAdminChannel(ch.id, { status_provider: value });
    await load();
  };

  const handleDelete = async (ch: AdminChannel) => {
    try {
      await deleteAdminChannel(ch.id);
      setNotice(`${ch.name} 채널을 목록에서 내렸습니다. (지난 회의 기록은 그대로 남습니다)`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleProbe = async (ch: AdminChannel) => {
    setProbing(ch.id);
    try {
      const res = await probeAdminChannel(ch.id);
      setProbeResult((prev) => ({ ...prev, [ch.id]: res.detail }));
    } catch (e) {
      setProbeResult((prev) => ({ ...prev, [ch.id]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setProbing(null);
    }
  };

  return (
    <div className="space-y-8 p-4 md:p-6" data-testid="admin-channels">
      <header>
        <h1 className="text-xl font-bold text-text-primary">채널 관리</h1>
        <p className="mt-1 text-sm text-text-secondary">
          이 서비스가 자막을 만들 생중계 채널입니다. 생중계 페이지 주소를 넣으면 영상 주소를 찾아 줍니다.
        </p>
      </header>

      {error && <Callout variant="error">{error}</Callout>}
      {notice && <Callout variant="info">{notice}</Callout>}

      {/* ① 의회 고르기 → ② 자동 찾기 */}
      <section className="rounded-lg border border-border bg-surface p-4" data-testid="discover-card">
        <h2 className="text-base font-semibold text-text-primary">채널 자동 찾기</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,320px)_1fr_auto] md:items-end">
          <label className="block text-sm">
            <span className="text-text-secondary">의회 고르기</span>
            <Select
              aria-label="의회 고르기"
              value=""
              onChange={(e) => {
                const found = presets.find((p) => p.name === e.target.value);
                if (found?.live_page) setPageUrl(found.live_page);
                else if (found) setPageUrl(found.homepage);
              }}
            >
              <option value="">직접 입력</option>
              <optgroup label="광역의회">
                {presetGroups.wide.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                    {p.live_page ? '' : ' (주소 확인 필요)'}
                  </option>
                ))}
              </optgroup>
              <optgroup label="경기도 시·군의회">
                {presetGroups.local.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                    {p.live_page ? '' : ' (주소 확인 필요)'}
                  </option>
                ))}
              </optgroup>
            </Select>
          </label>
          <label className="block text-sm">
            <span className="text-text-secondary">생중계 페이지 주소</span>
            <Input
              value={pageUrl}
              onChange={(e) => setPageUrl(e.target.value)}
              placeholder="https://<의회>/onair/onair.do"
            />
          </label>
          <Button onClick={handleDiscover} disabled={discovering || !pageUrl.trim()}>
            {discovering ? '찾는 중…' : '채널 자동 찾기'}
          </Button>
        </div>

        {discovery && (
          <div className="mt-4 space-y-3" data-testid="discover-result">
            {discovery.warnings.map((w) => (
              <Callout key={w} variant="warning">
                {w}
              </Callout>
            ))}

            {discovery.candidates.length > 0 ? (
              <>
                <table className="w-full text-sm">
                  <thead className="text-left text-text-secondary">
                    <tr>
                      <th className="w-10" />
                      <th className="py-1">채널 이름</th>
                      <th className="py-1">채널 ID</th>
                      <th className="py-1">확인</th>
                      <th className="py-1">영상 주소</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discovery.candidates.map((c) => (
                      <tr key={c.suggested_id} className="border-t border-border">
                        <td className="py-1">
                          <input
                            type="checkbox"
                            aria-label={`${c.name} 선택`}
                            checked={!!picked[c.suggested_id]}
                            onChange={(e) =>
                              setPicked((p) => ({ ...p, [c.suggested_id]: e.target.checked }))
                            }
                          />
                        </td>
                        <td className="py-1">{c.name}</td>
                        <td className="py-1 font-mono text-xs">{c.suggested_id}</td>
                        <td className="py-1 text-xs">
                          {c.verified === true ? (
                            <span className="text-success">재생목록 확인됨</span>
                          ) : (
                            <span className="text-text-secondary">
                              응답 없음 (방송 전일 수 있음)
                            </span>
                          )}
                        </td>
                        <td className="max-w-[24rem] truncate py-1 font-mono text-xs text-text-secondary">
                          {c.m3u8_url}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Button onClick={handleSaveDiscovered}>선택한 채널 등록</Button>
              </>
            ) : (
              <p className="text-sm text-text-secondary">
                읽은 주소 {discovery.fetched.length}개에서 영상 주소를 찾지 못했습니다. 아래에서 직접 넣어 주세요.
              </p>
            )}

            <details className="text-xs text-text-secondary">
              <summary className="cursor-pointer">무엇을 읽었는지 보기</summary>
              <ul className="mt-1 space-y-0.5">
                {discovery.fetched.map((f) => (
                  <li key={f.url} className="font-mono">
                    [{f.status ?? '실패'}] {f.url}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </section>

      {/* ③ 직접 입력 — 자동 찾기가 안 될 때의 확실한 길 */}
      <section className="rounded-lg border border-border bg-surface p-4" data-testid="manual-card">
        <h2 className="text-base font-semibold text-text-primary">영상 주소 직접 넣기</h2>
        <p className="mt-1 text-xs text-text-secondary">
          브라우저 개발자도구(F12) → 네트워크 탭에서 <code>m3u8</code> 로 걸러 보면 방송 중에 주소가 보입니다.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-[140px_200px_1fr_auto] md:items-end">
          <label className="block text-sm">
            <span className="text-text-secondary">채널 ID</span>
            <Input
              value={manual.id}
              onChange={(e) => setManual({ ...manual, id: e.target.value })}
              placeholder="ch1"
            />
          </label>
          <label className="block text-sm">
            <span className="text-text-secondary">채널 이름</span>
            <Input
              value={manual.name}
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
              placeholder="본회의"
            />
          </label>
          <label className="block text-sm">
            <span className="text-text-secondary">영상 주소 (.m3u8)</span>
            <Input
              value={manual.stream_url}
              onChange={(e) => setManual({ ...manual, stream_url: e.target.value })}
              placeholder="https://cdn.example/live/ch1/playlist.m3u8"
            />
          </label>
          <Button onClick={handleManualAdd}>등록</Button>
        </div>
      </section>

      {/* 등록된 채널 */}
      <section>
        <h2 className="mb-2 text-base font-semibold text-text-primary">
          등록된 채널 {items.length > 0 && <span className="text-text-secondary">({items.length})</span>}
        </h2>
        {loading ? (
          <p className="text-sm text-text-secondary">불러오는 중…</p>
        ) : items.length === 0 ? (
          <Callout variant="warning">
            등록된 채널이 없습니다. 채널이 없으면 자막이 시작되지 않습니다 — 위에서 하나 등록해 주세요.
          </Callout>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-text-secondary">
              <tr>
                <th className="py-1">이름</th>
                <th className="py-1">ID</th>
                <th className="py-1">방송 판정</th>
                <th className="py-1">영상 주소</th>
                <th className="py-1">상태</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {items.map((ch) => (
                <tr key={ch.id} className="border-t border-border align-top">
                  <td className="py-1.5">{ch.name}</td>
                  <td className="py-1.5 font-mono text-xs">{ch.id}</td>
                  <td className="py-1.5">
                    <Select
                      aria-label={`${ch.name} 방송 판정 방식`}
                      value={ch.status_provider}
                      onChange={(e) => handleProvider(ch, e.target.value)}
                    >
                      {PROVIDERS.map((p) => (
                        <option key={p.value} value={p.value}>
                          {PROVIDER_LABEL[p.value]}
                        </option>
                      ))}
                    </Select>
                  </td>
                  <td className="max-w-[20rem] truncate py-1.5 font-mono text-xs text-text-secondary">
                    {ch.stream_url || '—'}
                    {probeResult[ch.id] && (
                      <div className="mt-0.5 not-italic text-text-primary">{probeResult[ch.id]}</div>
                    )}
                  </td>
                  <td className="py-1.5 text-xs">{ch.is_active ? '쓰는 중' : '내림'}</td>
                  <td className="space-x-1 py-1.5 text-right">
                    <Button size="sm" variant="secondary" onClick={() => handleProbe(ch)} disabled={probing === ch.id}>
                      {probing === ch.id ? '확인 중' : '지금 확인'}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => handleToggleActive(ch)}>
                      {ch.is_active ? '내리기' : '올리기'}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => handleDelete(ch)}>
                      삭제
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default function AdminChannelsPage() {
  return (
    <RoleGuard roles={['admin']}>
      <ChannelAdmin />
    </RoleGuard>
  );
}
