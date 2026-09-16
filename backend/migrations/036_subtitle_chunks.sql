-- 036: 회의 자막 조각 임베딩 — AI 대화의 "뜻으로 찾기"(벡터+키워드 혼합 검색) (2026-09-15)
--
-- 배경: AI 대화는 질문 낱말이 자막에 그대로 있어야만 찾았다("휴대폰으로 쓰는 공무원 신분증" ≠ "모바일 공무원증").
-- 회의 자막을 발언자·안건 경계로 700자 안팎 조각으로 나눠 임베딩(text-embedding-3-large, 1536차원)을 저장하고,
-- 질문 임베딩과 가까운 조각을 회의 안에서 정확 검색(match_subtitle_chunks)한다. 키워드 검색과 순위를 합친다(RRF).
--   subtitle_chunks       회의별 조각(seq 순) — content 는 임베딩한 문장(머리+발언자 줄), content_hash 로 바뀐 조각만 다시 임베딩
--   subtitle_chunk_state  회의별 지문(자막 수·글자 수·해시) — 자막이 바뀌면 다시 만든다
-- 한 회의 안에서만 찾으므로(중앙값 약 90조각) ANN 인덱스는 만들지 않는다. pgvector 0.6.0 은 필터 뒤 HNSW 가 결과를 덜 돌려준다.
--
-- 적용 순서: ★배포보다 먼저★, ★생중계가 없을 때★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 스키마 캐시 — PGRST_DB_CHANNEL_ENABLED=false 라 NOTIFY 는 안 먹는다. 재시작은 생중계 자막 입력을 끊는다)
SET search_path = subtitle, public;   -- vector 형·<=> 연산자는 public(pgvector 0.6.0)

CREATE TABLE IF NOT EXISTS subtitle_chunks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id    UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,                       -- 조각을 만든 자막 종류(ai | live)
  seq           INT  NOT NULL,
  start_time    DOUBLE PRECISION NOT NULL,
  end_time      DOUBLE PRECISION NOT NULL,
  speakers      TEXT[] NOT NULL DEFAULT '{}',
  agenda_num    INT,
  content       TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  model         TEXT NOT NULL,
  embedding     public.vector(1536) NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (meeting_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_subtitle_chunks_meeting ON subtitle_chunks (meeting_id);

CREATE TABLE IF NOT EXISTS subtitle_chunk_state (
  meeting_id   UUID PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL,
  fingerprint  TEXT NOT NULL,
  model        TEXT NOT NULL,
  chunk_count  INT  NOT NULL,
  indexed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 회의 하나 안에서 질문 임베딩과 가까운 조각(코사인 유사도 = 1 - 거리). k 는 1~50.
CREATE OR REPLACE FUNCTION match_subtitle_chunks(p_meeting_id uuid, p_query public.vector(1536), p_k int DEFAULT 12)
RETURNS TABLE (seq int, start_time double precision, end_time double precision,
               speakers text[], agenda_num int, similarity double precision)
LANGUAGE sql STABLE
SET search_path = subtitle, public
AS $$
  SELECT c.seq, c.start_time, c.end_time, c.speakers, c.agenda_num, 1 - (c.embedding <=> p_query)
    FROM subtitle_chunks c
   WHERE c.meeting_id = p_meeting_id
   ORDER BY c.embedding <=> p_query
   LIMIT least(greatest(p_k, 1), 50)
$$;

COMMENT ON TABLE subtitle_chunks IS 'AI 대화 뜻으로 찾기용 자막 조각 임베딩(text-embedding-3-large·1536). services/subtitle_embeddings';
COMMENT ON TABLE subtitle_chunk_state IS '회의별 조각 지문 — 자막이 바뀌면 조각을 다시 만든다. services/embedding_pregen';

-- superuser 로 만든 객체의 소유권을 전용 롤로 (템플릿 규약)
DO $ownership$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ggc_subtitle') THEN
    EXECUTE 'ALTER TABLE subtitle.subtitle_chunks OWNER TO ggc_subtitle';
    EXECUTE 'ALTER TABLE subtitle.subtitle_chunk_state OWNER TO ggc_subtitle';
    EXECUTE 'ALTER FUNCTION subtitle.match_subtitle_chunks(uuid, public.vector, int) OWNER TO ggc_subtitle';
  END IF;
END
$ownership$;
