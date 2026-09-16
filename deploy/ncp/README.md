# NCP PoC(k3s) 배포 런북 — 실시간 자막 서비스

경기도의회 업무플랫폼 검증환경(poc-app k3s + poc-db PostgreSQL 16)으로의 이관 파이프라인.
인프라 절차는 기관의 인프라 문서를 따른다.
이 디렉터리의 스크립트는 정본 `scripts/06~09·11` 의 복제·개명판이며, 전송·실행 규칙도 동일하다.

## 전제 (로컬 Git Bash, cwd = 저장소 루트)

**서버 주소는 저장소에 없다.** `deploy/ncp/env.sh` 에서 읽는다(`.gitignore` 대상).
처음 한 번만 `cp deploy/ncp/env.sh.example deploy/ncp/env.sh` 후 실제 값을 채운다.

```bash
. deploy/ncp/env.sh
APP="$GGC_APP_HOST"
SSH="ssh -i $GGC_SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=no \
     -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
     -o ServerAliveInterval=30 -o ServerAliveCountMax=20"
NORM="sed -e 1s/^\xef\xbb\xbf// -e s/\r$//"
DB="$SSH -J $APP"
```

**서버에서 도는 스크립트는 로컬 `env.sh` 를 못 읽는다** — 필요한 값을 명령 앞에 붙여 넘긴다.
값이 없으면 스크립트가 **중단된다**(조용히 엉뚱한 곳에 붙는 것보다 낫다).

| 스크립트 | 넘겨야 하는 값 |
|---|---|
| `35-deploy.sh` | `GGC_PUBLIC_IP` (CORS_ORIGINS 주입) |
| `40-verify-transcribe.sh` | `GGC_LB_IP` · `GGC_PUBLIC_IP` |
| `31`·`31b`·`50` | `GGC_DB_HOST` |
| `30-provision-db.sh` | `GGC_APP_SUBNET` (pg_hba 허용 대역) |

- **`bash -s` 금지** — `cat > /tmp/파일` 후 `bash 파일 < /dev/null` 로 실행한다(apt 가 stdin 을 먹는다).
- 대화형 예외는 25·31 뿐이다(`ssh -t` 로 접속해 TTY 입력).
- `.sh`/`.sql` 은 BOM 없는 LF. 전송 파이프의 `$NORM` 이 한 번 더 정규화한다.

## Phase A — 실행부 이관 (DB 는 Supabase 유지)

```bash
# 1) 소스 전송 (로컬)
bash deploy/ncp/10-sync-source.sh

# 2) 이미지 빌드 (poc-app, sudo)
$NORM deploy/ncp/20-build-images.sh | $SSH $APP 'cat > /tmp/transcribe-20.sh'
$SSH $APP 'sudo -n bash /tmp/transcribe-20.sh < /dev/null' < /dev/null

# 3) 런타임 Secret (poc-app, 대화형 — JWT 는 없을 때만 생성된다)
$NORM deploy/ncp/25-set-runtime-secret.sh | $SSH $APP 'cat > /tmp/transcribe-25.sh'
ssh -t -i "$GGC_SSH_KEY" $APP 'bash /tmp/transcribe-25.sh'

# 4) 1단계 배포 — 워크로드만 (Ingress 없음)
$NORM deploy/ncp/35-deploy.sh | $SSH $APP 'cat > /tmp/transcribe-35.sh'
$SSH $APP "GGC_PUBLIC_IP=$GGC_PUBLIC_IP bash /tmp/transcribe-35.sh < /dev/null" < /dev/null

# 5) 검증 → 전 항목 PASS 후에만 2단계
$NORM deploy/ncp/40-verify-transcribe.sh | $SSH $APP 'cat > /tmp/transcribe-40.sh'
$SSH $APP "GGC_LB_IP=$GGC_LB_IP GGC_PUBLIC_IP=$GGC_PUBLIC_IP bash /tmp/transcribe-40.sh < /dev/null" < /dev/null

# 6) 2단계 노출 (선행: ACG 에 허용 출발지 등록 — 사람 단계 H1·H2)
$SSH $APP "EXPOSE=1 GGC_PUBLIC_IP=$GGC_PUBLIC_IP bash /tmp/transcribe-35.sh < /dev/null" < /dev/null
```

## Phase B — DB 컷오버 (선행: 코드 트랙의 DB_BACKEND=postgres 전 API 커버)

```bash
# 1) poc-db 프로비저닝 (점프 경유, sudo)
$NORM deploy/ncp/30-provision-db.sh    | $DB ncloud@<poc-db 사설 IP> 'cat > /tmp/transcribe-30.sh'
$NORM deploy/ncp/sql/V1__provision.sql | $DB ncloud@<poc-db 사설 IP> 'cat > /tmp/transcribe-V1.sql'
$DB ncloud@<poc-db 사설 IP> 'sudo -n bash /tmp/transcribe-30.sh < /dev/null' < /dev/null

# 2) 데이터 이관 (poc-app, 대화형 — Supabase 비밀번호는 TTY 입력만)
$NORM deploy/ncp/31-import-data.sh | $SSH $APP 'cat > /tmp/transcribe-31.sh'
ssh -t -i "$GGC_SSH_KEY" $APP 'sudo bash /tmp/transcribe-31.sh'

# 3) Secret 에 DATABASE_URL 추가
ssh -t -i "$GGC_SSH_KEY" $APP 'bash /tmp/transcribe-25.sh --phase-b'

# 4) postgres 모드 배포 + 검증
$SSH $APP 'DB_BACKEND=postgres bash /tmp/transcribe-35.sh < /dev/null' < /dev/null
$SSH $APP 'EXPECT_DB_BACKEND=postgres bash /tmp/transcribe-40.sh < /dev/null' < /dev/null
```

## 롤백

```bash
$NORM deploy/ncp/90-rollback.sh | $SSH $APP 'cat > /tmp/transcribe-90.sh'
$SSH $APP 'bash /tmp/transcribe-90.sh --list < /dev/null' < /dev/null
# 앱 결함  → --tag <직전태그>
# DB 결함  → DB_BACKEND=supabase bash /tmp/transcribe-35.sh  (Supabase 는 freeze 상태로 존치)
# 긴급 차단 → --close (Ingress 만 제거, 수 초)
```

## _template 표준 대비 명시적 예외 (근거: STT 워커 특성)

| # | 표준 | 예외 | 근거 |
|---|---|---|---|
| E1 | CPU limit 500m | api 2000m | ffmpeg 실시간 디코딩 1~2채널 + diarize 버스트 |
| E2 | MEM limit 512Mi | api 3Gi | kiwipiepy 상주(~1GB) + PCM/mp3 롤링 버퍼 |
| E3 | 스토리지 없음 | uploads PVC 5Gi | 안건·속기 업로드 자산 영속 |
| E4 | 단일 Deployment | web+api 2개 | Next SSR 과 FastAPI 워커 분리(저장소 설계 유지) |
| E5 | grace 30s | api 60s + preStop 5s | WS 장기연결 drain |
| E6 | probe /<svc>/healthz | api /health · web /transcribe/login | 앱 계약 유지(코드 무변경 원칙) |
| E7 | envFrom db-credentials | 전용 Secret 의 DATABASE_URL | 최소권한 — 전용 롤 ggc_subtitle |

표준 유지 항목: readOnlyRootFS · caps drop ALL · seccomp RuntimeDefault ·
automountServiceAccountToken:false · 숫자 UID · latest 금지 · HSTS 금지 · 2단계 노출.

## 운영 불변식

- **`STT_AUTO_START=true` 가 정상이다** (2026-08-22 전환). 방송 시작을 감지해 자동으로
  자막을 만든다. 끄면 방송이 열려도 자막이 안 나오는데, 화면에 수동 시작 버튼이 없어
  아무도 모른 채 회의가 끝난다. 40-verify 가 `true` 를 확인한다.
  - 컷오버(08-18) 전에는 반대로 `false` 가 필수였다 — Railway 프로덕션이 같은 Supabase 를
    보고 있어 이중 STT 기록·이중 과금이 났기 때문. Railway 소멸·DB 분리로 그 사유는 끝났다.
- **동시 STT 채널 상한은 14** (상임위 13 + 본회의). 낮추지 말 것 —
  8이던 2026-07-21 에 12개 상임위 동시 방송에서 시청자 50명 채널이 정회 속개 때
  시청자 0명 채널에 슬롯을 뺏겨 자막이 안 나온 사고가 있었다.
  비용: 채널당 ~$0.4/시간, 최악(전 상임위 동시) ~$5.6/시간 → **OpenAI 월 하드 리밋이 상한선.**
- **OpenAI 월 하드 리밋을 반드시 건다.** 자동 자막을 켠 이상 **월 총액을 막는 장치는 이것뿐이다**
  — 앱의 동시 채널 상한과 무음 구간 호출 생략은 순간 부하만 누른다.
  한도는 기관의 최번월 실사용량을 재서 그 몇 배로 잡고, 차단 전에 알림이 오도록 경고선을 함께 건다
  (한도를 넘으면 API 가 막혀 **자막이 멈춘다**).
  사용량 확인: `/<서비스경로>/admin/usage` (오디오 시간 × 단가 추정치, 실청구액은 OpenAI 대시보드).
- JWT_SECRET_KEY·TLS 인증서·기존 Secret 은 재생성하지 않는다(전 세션 무효·지문 변경).
- 접근통제 주 방어선은 **클라우드 보안그룹**이다. 443 은 필요한 출발지만, 관리 포트(22)는 단일 주소로 좁힌다.
