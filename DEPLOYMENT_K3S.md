# 실시간 자막 서비스 K3s 배포 (Phase 1)

## 범위

Phase 1은 web/API 실행부만 K3s로 이전합니다. Supabase REST·RLS·Realtime 데이터 계약은 유지하며, `poc-db` 이관은 별도 Phase 2입니다.

## 안전 설계

- `/transcribe`는 기존 `/`, `/hr`, `/ops`와 독립된 Deployment·Service·Ingress입니다.
- API는 한 replica만 사용합니다. 라이브 STT, 비동기 작업, WebSocket broadcast가 현재 process-local이기 때문입니다.
- `STT_AUTO_START=true` 입니다(2026-08-22 사용자 결정 — 끄면 방송이 열려도 자막이 안 나온다). 비용 상한은 OpenAI 월 하드리밋 $500. `VOD_AUTO_STT_*`(2026-09-03)로 새벽 AI 자막 자동 생성이 하루 10건 상한으로 돕니다.
- 업로드 파일은 `/app/uploads`의 단일-writer PVC로 보존합니다. 이 PVC는 노드 로컬 `local-path`(5Gi, reclaim `Delete`)이므로 workload 삭제 전 필요한 업로드 자료를 별도로 백업해야 합니다.
- runtime Secret은 `ggc-live-transcribe-runtime`만 참조합니다. 기존 Secret을 재사용하지 않습니다.

## Secret key 계약

Secret에는 아래 키만 필요합니다. 값은 이 문서·Git·채팅에 기록하지 않습니다.

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `OPENAI_API_KEY`
- `JWT_SECRET_KEY`
- `ADMIN_QUICK_PIN`

## 사전 검증

```bash
kubectl apply --dry-run=client -f k8s/ggc-live-transcribe.yaml
```

실제 적용 전에 이미지 SHA를 manifest의 두 `REPLACE_WITH_GIT_SHA` 위치에 반영해야 합니다.

## 배포 후 검증

- `kubectl -n ggc-poc rollout status deployment/ggc-live-transcribe-web`
- `kubectl -n ggc-poc rollout status deployment/ggc-live-transcribe-api`
- `https://<poc-app 공인 IP>/transcribe/login`
- `https://<poc-app 공인 IP>/transcribe/health`

## Rollback

새 workload만 제거합니다. 기존 문서 허브·HR·운영 포털에는 영향을 주지 않습니다.

```bash
kubectl -n ggc-poc delete -f k8s/ggc-live-transcribe.yaml
```

## Phase 2: poc-db 전환 선행 조건

원본 Supabase migration은 `supabase_realtime` publication을 사용합니다. PostgreSQL-only `poc-db`에 그대로 적용하지 않습니다. 전환 전에는 PostgreSQL 호환 schema, 전용 최소권한 role, 데이터 이관 검증, queue/worker, 분산 WebSocket fan-out을 별도 설계·검증해야 합니다.
