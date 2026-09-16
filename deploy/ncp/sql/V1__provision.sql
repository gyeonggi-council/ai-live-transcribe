-- =============================================================================
-- V1 · poc-db(ggcpoc) 자막 스키마 프로비저닝 (DDL 정본 — 30-provision-db.sh 가 실행)
--
-- 실행 주체: postgres 슈퍼유저 (poc-db 에서 sudo -u postgres)
-- 비밀번호는 이 파일에 없다 — /root/poc-db-credentials.txt 가 정본이고
-- 30-provision-db.sh 가 :subtitle_password 변수로 주입한다.
--
-- 설계 근거:
--  · DB 를 새로 만들지 않고 기존 ggcpoc 안에 subtitle 스키마로 격리(ggc-deploy 스킬 표준).
--    P4 통합(ggc_council.subtitle) 시 pg_dump -n subtitle 한 번으로 무변환 이관된다.
--  · extensions 스키마: Supabase 는 확장을 extensions 스키마에 설치하므로 라이브 덤프의
--    DEFAULT extensions.uuid_generate_v4() 표기가 그대로 통과하려면 같은 구조가 필요하다.
--  · subtitle_stage: 덤프를 public 으로 받아 subtitle 로 개명하는 중간 DB.
--    (자막 본문에 "public." 문자열이 있을 수 있어 텍스트 치환은 금지 — 스키마 개명으로 처리)
-- =============================================================================

-- 롤 (멱등: 없을 때만 생성, 비밀번호는 파일 정본에 맞춰 항상 동기화)
SELECT 'CREATE ROLE ggc_subtitle LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ggc_subtitle')
\gexec
ALTER ROLE ggc_subtitle WITH LOGIN PASSWORD :'subtitle_password';
ALTER ROLE ggc_subtitle SET search_path = subtitle, extensions, public;

-- ggcpoc 안의 스키마
\connect ggcpoc
CREATE SCHEMA IF NOT EXISTS subtitle AUTHORIZATION ggc_subtitle;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm     WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto    WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO ggc_subtitle;
-- 재이관 시 DROP SCHEMA subtitle CASCADE + CREATE SCHEMA 를 ggc_subtitle 이 직접 한다.
GRANT CREATE ON DATABASE ggcpoc TO ggc_subtitle;

-- 스테이징 DB (덤프 수신·스키마 개명용. 컷오버까지 롤백 소스로 유지)
SELECT 'CREATE DATABASE subtitle_stage OWNER ggc_subtitle'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'subtitle_stage')
\gexec
\connect subtitle_stage
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm     WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto    WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO ggc_subtitle;
