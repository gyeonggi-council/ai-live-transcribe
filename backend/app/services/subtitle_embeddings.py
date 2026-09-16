"""회의 자막 조각 임베딩 — AI 대화의 "뜻으로 찾기" (2026-09-15 담당자 요청 "회의 내용을 벡터화해서 AI 가 벡터로 질의").

키워드 검색(rag_context)은 질문 낱말이 자막에 그대로 있어야 찾는다. 여기서는 자막을 발언자·안건 경계로 700자 안팎 조각으로
나눠 임베딩을 저장하고(migration 036 subtitle_chunks), 질문 임베딩과 가까운 조각을 회의 안에서 찾는다(match_subtitle_chunks).
결과는 rag_context.build_meeting_context 의 후보에 합쳐진다(키워드 적중과 함께 점수 합산). 실패하면 키워드 검색만으로 답한다.

  build_embedding_chunks(subs, agendas) — 순수 함수(요약 청크 규칙 재사용 + 앞 조각 끝 겹침)
  index_meeting(supabase, meeting_id)   — 바뀐 조각만 다시 임베딩해 저장, 상태(지문) 갱신
  search(supabase, meeting_id, query)   — 질문 임베딩 1번 + RPC 1번
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBED_URL = "https://api.openai.com/v1/embeddings"
DIMENSIONS = 1536                 # pgvector 0.6.0 HNSW 상한(2000) 안 — 나중에 회의 간 검색에 인덱스를 걸 수 있게
_BATCH = 64
_INSERT_BATCH = 50
_MAX_CONTENT = 3000               # 한 행이 6천 자인 자막도 있다 — 임베딩 입력 상한 안으로


def _hms(sec: float) -> str:
    s = int(sec or 0)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def fingerprint(subs: list[dict], agendas: list[dict] | None = None) -> str:
    """조각을 만드는 입력 전체의 지문 — 자막(시각·끝 시각·화자·본문)과 안건(번호·제목). 하나라도 바뀌면 다시 만든다."""
    h = hashlib.sha1()
    for s in subs:
        h.update(f"{s.get('id')}|{s.get('start_time')}|{s.get('end_time')}|{s.get('speaker') or ''}|{s.get('text') or ''}\n".encode())
    for a in agendas or []:
        h.update(f"A|{a.get('order_num')}|{a.get('title') or ''}\n".encode())
    kinds = ",".join(sorted({str(s.get("kind") or "") for s in subs}))
    return f"{kinds}:{len(subs)}:{h.hexdigest()[:16]}"


def build_embedding_chunks(subs: list[dict], agendas: list[dict] | None) -> list[dict]:
    """조각 = 요약 청크 규칙(안건 경계·화자 교대·1.5배 강제)을 700자 목표로 + 앞 조각 끝 1~2행(200자 이내) 겹침.

    임베딩 문장: "안건 5. 제목 | 04:28:12~04:30:12 | 발언: 이자형 위원, 진용국 사무처장" + 같은 발언자 행을 이은 "이자형 위원: …" 줄.
    발언자·안건을 문장에 넣어 "이자형 위원이 모바일 공무원증 얘기한 곳"처럼 사람을 섞은 질문도 가깝게 나온다.
    """
    from app.services.summary_service import build_summary_chunks

    chunks = build_summary_chunks(subs, agendas, target_chars=700)
    out: list[dict] = []
    tail = ""
    for ch in chunks:
        rows = ch["subtitles"]
        speakers = list(dict.fromkeys((r.get("speaker") or "화자 미확인") for r in rows))
        head = (f"안건 {ch['order_num']}. {ch.get('title') or ''} | " if ch.get("order_num") else "")
        head += f"{_hms(ch['start_time'])}~{_hms(ch['end_time'])} | 발언: {', '.join(speakers[:4])}"
        body: list[str] = []
        for r in rows:
            spk = r.get("speaker") or "화자 미확인"
            text = (r.get("text") or "").strip()
            if not text:
                continue
            if body and body[-1].startswith(spk + ": "):
                body[-1] += " " + text
            else:
                body.append(f"{spk}: {text}")
        text = "\n".join(body)
        # 요약 청크는 자막 한 행을 자르지 않아 한 행이 수천 자인 조각이 있다 — 버리지 않고 같은 머리로 여러 조각에 나눠 담는다(Codex 검토)
        room = max(500, _MAX_CONTENT - len(head) - 260)
        parts = [text[k:k + room] for k in range(0, len(text), room)] or [""]
        for j, part in enumerate(parts):
            lead = tail if j == 0 else parts[j - 1][-200:]
            content = head + "\n" + (f"(앞) {lead}\n" if lead else "") + part
            out.append({
                "seq": len(out), "start_time": float(ch["start_time"]), "end_time": float(ch["end_time"]),
                "speakers": speakers[:12], "agenda_num": ch.get("order_num"), "content": content,
                "content_hash": hashlib.sha1(content.encode()).hexdigest(),
            })
        last = [(r.get("text") or "").strip() for r in rows[-2:]]
        tail = " ".join(t for t in last if t)[-200:]
    return out


def embed_texts(texts: list[str], *, timeout: float = 30.0) -> list[list[float]]:
    """OpenAI 임베딩(배치 64, 429·5xx 는 3번까지 물러났다 재시도). 실패하면 예외."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 없음")
    out: list[list[float]] = []
    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        for i in range(0, len(texts), _BATCH):
            batch = texts[i:i + _BATCH]
            for attempt in range(4):
                r = client.post(EMBED_URL, headers=headers, json={
                    "model": settings.rag_embedding_model, "input": batch, "dimensions": DIMENSIONS})
                if r.status_code == 200:
                    data = sorted(r.json()["data"], key=lambda d: d["index"])
                    out.extend([round(x, 6) for x in d["embedding"]] for d in data)
                    break
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"임베딩 실패 HTTP {r.status_code}: {r.text[:200]}")
    return out


def index_meeting(supabase: Any, meeting_id: str) -> dict:
    """회의 조각을 만들고 바뀐 조각만 임베딩해 저장한다. 지문이 같으면 아무것도 안 한다."""
    from app.services.subtitle_fetch import fetch_all_subtitles
    from app.services.subtitle_select import prefer_ai_subtitles

    subs = prefer_ai_subtitles(fetch_all_subtitles(supabase, meeting_id) or [])
    if not subs:
        return {"meeting_id": meeting_id, "skipped": "no_subtitles"}
    agendas = [a for a in (supabase.table("meeting_agendas").select("order_num, title").eq("meeting_id", meeting_id)
                           .order("order_num").execute().data or []) if a.get("title")]
    fp = fingerprint(subs, agendas)
    model = settings.rag_embedding_model
    state = (supabase.table("subtitle_chunk_state").select("fingerprint, model")
             .eq("meeting_id", meeting_id).limit(1).execute().data or [None])[0]
    now = datetime.now(timezone.utc).isoformat()
    if state and state.get("fingerprint") == fp and state.get("model") == model:
        # 회의 행만 바뀌고 자막은 그대로 — 확인 시각만 올려 다음 바퀴에 다시 뽑히지 않게
        supabase.table("subtitle_chunk_state").update({"indexed_at": now}).eq("meeting_id", meeting_id).execute()
        return {"meeting_id": meeting_id, "skipped": "unchanged"}
    chunks = build_embedding_chunks(subs, agendas or None)
    existing = {r["seq"]: r for r in (supabase.table("subtitle_chunks").select("seq, content_hash, model")
                                      .eq("meeting_id", meeting_id).execute().data or [])}
    todo = [c for c in chunks
            if not (existing.get(c["seq"], {}).get("content_hash") == c["content_hash"]
                    and existing.get(c["seq"], {}).get("model") == model)]
    vectors = embed_texts([c["content"] for c in todo]) if todo else []
    kind = "ai" if any(s.get("kind") == "ai" for s in subs) else "live"
    rows = [{"meeting_id": meeting_id, "kind": kind, "model": model, "embedding": v, **c} for c, v in zip(todo, vectors)]
    for i in range(0, len(rows), _INSERT_BATCH):
        supabase.table("subtitle_chunks").upsert(rows[i:i + _INSERT_BATCH], on_conflict="meeting_id,seq").execute()
    if len(existing) > len(chunks):
        supabase.table("subtitle_chunks").delete().eq("meeting_id", meeting_id).gte("seq", len(chunks)).execute()
    supabase.table("subtitle_chunk_state").upsert({
        "meeting_id": meeting_id, "kind": kind, "fingerprint": fp, "model": model, "chunk_count": len(chunks),
        "indexed_at": now,
    }, on_conflict="meeting_id").execute()
    return {"meeting_id": meeting_id, "chunks": len(chunks), "embedded": len(todo)}


def search(supabase: Any, meeting_id: str, query: str, k: int = 12) -> list[dict]:
    """질문과 뜻이 가까운 조각 [{seq, start_time, end_time, speakers, agenda_num, similarity}] — 조각이 없으면 []."""
    vec = embed_texts([query[:2000]], timeout=10.0)[0]
    res = supabase.rpc("match_subtitle_chunks", {"p_meeting_id": meeting_id, "p_query": vec, "p_k": k}).execute()
    return list(res.data or [])
