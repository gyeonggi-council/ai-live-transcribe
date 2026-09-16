# 실서버 배포 가이드 (상시 가동 호스트)

Railway 대체 — **상시 가동 + 한국(서울) 리전 + KMS 접근 가능** 구성.
라이브 자막 writer는 WebSocket/ffmpeg 데몬이라 Vercel(서버리스)에서 못 돌리므로 별도 상시 호스트가 필요하다.

> 이 문서는 **Oracle Cloud Always Free(서울)** 예시다. `deploy/`의 docker-compose + nginx + scripts는
> 클라우드 비종속이라 **네이버 클라우드(NCP) Ubuntu 서버**에도 그대로 적용된다.
> NCP의 경우: Server(Ubuntu 22.04) 생성 → 공인 IP/ACG에서 80·443 허용 → 이후 Phase 2부터 동일.

## 구성도

```
[Vercel Frontend]  ──https──▶  api.your-domain.com (서울 리전 VM)
                                      │
                               [nginx :443]
                               SSL 종단 + WebSocket upgrade
                                      │
                               [FastAPI :8000]  (+ ffmpeg)
                                      │
                    ┌────────────┬────┴────────────────┐
                    ▼            ▼                     ▼
                [Supabase]   [OpenAI STT/AI]      [KMS 조회 ✓]
                            realtime-whisper +
                            4o-transcribe-diarize
```

---

## Phase 0 · 사전 준비 (30분)

### 0.1 Oracle Cloud 계정 생성
1. https://cloud.oracle.com 접속 → 한국어 가입
2. **지역(Region): 서울 (`ap-seoul-1`)** 선택 ⚠️ 가입 후 변경 불가
3. 신용카드 등록 필요 (과금 없음, 본인확인용 — Always Free만 쓰면 $0)

### 0.2 도메인 확보 (선택 3가지)
| 방식 | 비용 | 설명 |
|------|------|------|
| 도메인 구매 | 연 1~2만원 | Cafe24/Gabia/Porkbun — `api.your-brand.kr` |
| DuckDNS | 무료 | `ggc-subtitle.duckdns.org` (공공기관 운영엔 비권장) |
| 기존 도메인 서브도메인 | 무료 | 이미 도메인 있으면 `api.` 서브 추가 |

### 0.3 로컬에 SSH 키 생성 (없다면)
```bash
ssh-keygen -t ed25519 -C "oci-ggc" -f ~/.ssh/oci-ggc
# 공개키 출력 (OCI 인스턴스 생성 시 붙여넣기)
cat ~/.ssh/oci-ggc.pub
```

---

## Phase 1 · VM 프로비저닝 (15분)

### 1.1 Compute Instance 생성
1. OCI 콘솔 → **Compute > Instances > Create instance**
2. 설정:
   - **Name**: `ggc-subtitle-api`
   - **Image**: Canonical Ubuntu **22.04** (ARM64)
   - **Shape**: `VM.Standard.A1.Flex` (**Always Free** 대상)
     - OCPU: **4** (최대)
     - Memory: **24 GB** (최대)
   - **Networking**: Create new VCN (기본값 OK)
   - **SSH keys**: Paste public keys → 위에서 생성한 `oci-ggc.pub` 붙여넣기
   - **Boot volume**: 50 GB (기본)
3. Create

### 1.2 공인 IP 확인
생성 완료 후 인스턴스 상세 페이지에서 **Public IP address** 기록.

### 1.3 보안 목록에서 80/443 허용 ⚠️ 필수
1. 인스턴스 상세 > **Primary VNIC > Subnet > Security Lists**
2. Default Security List > **Add Ingress Rules**
3. 추가:
   - Source CIDR: `0.0.0.0/0`, Destination Port: `80`, Description: "HTTP"
   - Source CIDR: `0.0.0.0/0`, Destination Port: `443`, Description: "HTTPS"

### 1.4 DNS A 레코드 설정
도메인 등록기관(Cafe24/Gabia/Cloudflare)에서:
```
타입: A
이름: api   (or api.your-brand.kr)
값: <OCI 공인 IP>
TTL: 300
```
전파 확인:
```bash
dig +short api.your-brand.kr
# → OCI 공인 IP가 나와야 함 (최대 10분 소요)
```

---

## Phase 2 · VM 초기 셋업 (10분)

### 2.1 SSH 접속
```bash
ssh -i ~/.ssh/oci-ggc ubuntu@<OCI 공인 IP>
```

### 2.2 초기 셋업 스크립트 실행
```bash
# 저장소 받기
git clone https://github.com/gyeonggi-council/ggc-subtitle.git /tmp/ggc-clone

# OCI 초기 셋업 (Docker, 방화벽, 스왑, fail2ban)
sudo /tmp/ggc-clone/deploy/scripts/oci-setup.sh
```

완료 메시지가 나오면:
```bash
# docker 그룹 반영을 위해 재로그인
exit
ssh -i ~/.ssh/oci-ggc ubuntu@<OCI 공인 IP>
```

### 2.3 배포 디렉토리로 저장소 이동
```bash
sudo mv /tmp/ggc-clone /opt/ggc-subtitle/repo
sudo chown -R ubuntu:ubuntu /opt/ggc-subtitle
cd /opt/ggc-subtitle/repo
```

---

## Phase 3 · 환경변수 설정 (5분)

### 3.1 환경변수 준비
노트북에서 검증할 때 쓰던 `backend/.env` 값을 그대로 가져오거나, 아래 항목을 준비한다.

### 3.2 서버에 .env 파일 작성
```bash
cp /opt/ggc-subtitle/repo/backend/.env.example /opt/ggc-subtitle/repo/backend/.env
vim /opt/ggc-subtitle/repo/backend/.env
```

필수 항목 (Deepgram 제거됨 — STT는 OpenAI 전면 사용):
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJ...
DATABASE_URL=postgresql://postgres:...@db.your-project.supabase.co:5432/postgres
OPENAI_API_KEY=sk-...                    # 라이브(realtime-whisper)+화자구분/VOD(4o-transcribe-diarize)+AI 공용
JWT_SECRET_KEY=$(openssl rand -hex 32)   # 새로 발급 권장
CORS_ORIGINS=["https://ggcsubai.vercel.app"]
STT_AUTO_START=true
DEBUG=false
```

---

## Phase 4 · SSL 발급 + 배포 (10분)

### 4.1 SSL 인증서 발급
```bash
cd /opt/ggc-subtitle/repo/deploy
sudo ./scripts/init-ssl.sh api.your-brand.kr admin@your-brand.kr
```

성공 메시지: `✅ SSL 발급 및 HTTPS 설정 완료`

### 4.2 백엔드 기동
```bash
cd /opt/ggc-subtitle/repo/deploy
docker compose up -d
```

### 4.3 동작 확인
```bash
# 헬스체크
curl https://api.your-brand.kr/health
# → {"status":"ok"}

# API 조회
curl https://api.your-brand.kr/api/channels/status | jq '.[0:2]'

# WebSocket (wscat 설치: npm install -g wscat)
wscat -c wss://api.your-brand.kr/ws/meetings/ch1/subtitles

# KMS 접근 테스트 (한국 IP로 요청됨)
docker compose exec api python -c "
import httpx
r = httpx.get('https://kms.ggc.go.kr', timeout=10)
print('KMS status:', r.status_code)
"
```

---

## Phase 5 · 프론트엔드 연결 (5분)

### 5.1 Vercel 환경변수 업데이트
Vercel 대시보드 → frontend 프로젝트 → Settings > Environment Variables:
```
NEXT_PUBLIC_API_URL = https://api.your-brand.kr
NEXT_PUBLIC_WS_URL  = wss://api.your-brand.kr
```
**Production / Preview / Development 3환경 모두 적용.**

### 5.2 재배포
```bash
cd frontend
npx vercel --prod --yes
```

---

## 일상 운영

### 코드 업데이트 배포
```bash
ssh -i ~/.ssh/oci-ggc ubuntu@<IP>
cd /opt/ggc-subtitle/repo
./deploy/scripts/deploy.sh
```

### 로그 확인
```bash
cd /opt/ggc-subtitle/repo/deploy
docker compose logs -f api       # 백엔드 로그
docker compose logs -f nginx     # 프록시 로그
docker compose ps                # 전체 상태
```

### 재시작
```bash
docker compose restart api
```

### SSL 인증서 수동 갱신 (자동이 실패한 경우)
```bash
docker compose run --rm certbot renew
docker compose exec nginx nginx -s reload
```

---

## 모니터링 + 백업

### 디스크 사용량
OCI Always Free는 부트 50GB + 데이터 볼륨 최대 200GB.
```bash
df -h /
docker system df   # 이미지/볼륨 사용량
```

### 업로드 볼륨 백업 (선택)
```bash
# 주간 백업 예시 (cron)
tar -czf /var/ggc-backups/uploads-$(date +%Y%m%d).tar.gz /var/ggc-data/uploads
```

### 리소스 모니터링
```bash
htop              # CPU/메모리
docker stats      # 컨테이너별 리소스
journalctl -u docker --since "1h ago"
```

---

## 트러블슈팅

### 80/443 타임아웃
- OCI 콘솔 **Security List**에서 80/443 Ingress Rule 확인
- VM 내부: `sudo ufw status` → 80/443 ALLOW 있어야 함
- `sudo iptables -L -n` → ACCEPT 규칙 있어야 함

### KMS 403/404
- 서울 리전인지 확인: `curl ifconfig.co/country` → `South Korea`
- 다른 리전이면 마이그레이션 재수행 (리전 변경 불가, VM 재생성 필요)

### OCI Always Free 계정 정지 경고 메일
- 인스턴스가 **>7일 idle**이면 reclaim 경고 발생
- 예방: `crontab -e`에 시간당 1회 curl 작업 추가
  ```
  0 * * * * curl -s https://api.your-brand.kr/health > /dev/null
  ```
  (이미 앱이 self-ping 하므로 대개 충분)

### Docker 이미지 빌드가 느림 (ARM)
- 멀티 아키텍처 빌드가 ARM에서 느릴 때는 로컬(AMD) 빌드 후 푸시 방식 고려
- 또는 `BUILDKIT_INLINE_CACHE=1` 빌드 캐시 활용

---

## 비용 요약

| 항목 | 비용 |
|------|------|
| Compute VM.Standard.A1.Flex (4 OCPU, 24GB) | **$0** (Always Free) |
| Block Volume 50GB | **$0** (Always Free) |
| 아웃바운드 트래픽 10TB/월 | **$0** (Always Free) |
| Let's Encrypt SSL | **$0** |
| 도메인 | 연 1~2만원 |
| Supabase/OpenAI | 기존 그대로 (사용량 과금) |
| **합계** | **도메인 비용만** |

---

## 롤백 계획

서버 전환 후 문제 발생 시:
1. Vercel 환경변수 `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL`을 직전 동작하던 호스트로 원복
2. 또는 노트북에서 `backend`를 직접 기동(`uvicorn app.main:app`)하고 터널(예: cloudflared)로 임시 노출

VM은 유지해두면 언제든 다시 전환 가능.
