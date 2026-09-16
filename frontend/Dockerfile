# syntax=docker/dockerfile:1
FROM docker.io/library/node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM docker.io/library/node:22-bookworm-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_BASE_PATH=/transcribe
# SSR(서버측 fetch)용 절대 URL — 클러스터 내부 Service DNS. 브라우저는 basePath 접두 same-origin 을 쓴다.
ARG NEXT_PUBLIC_API_URL=http://ggc-live-transcribe-api
# 빈 값 = 접속한 주소를 따라감(same-origin). IP·도메인(aisub.ggc.go.kr) 모두 자연 동작.
ARG NEXT_PUBLIC_WS_URL=
# 라이브 영상을 라이브 엣지에서 일부러 늦추는 초(자막이 항상 먼저 준비되게). 빌드 시 인라인 —
# 파드 env 로는 안 바뀐다. 값의 근거·조정 규칙은 CLAUDE.md "라이브 영상-자막 동기화" 절.
# 비우면 HlsPlayer.tsx 의 코드 기본값을 쓴다.
ARG NEXT_PUBLIC_LIVE_SYNC_SEC=
ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH} \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_PUBLIC_LIVE_SYNC_SEC=${NEXT_PUBLIC_LIVE_SYNC_SEC}
RUN npm run build

FROM docker.io/library/node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
# node 이미지의 기본 사용자(node)와 동일한 UID. 숫자로 써야 k8s runAsNonRoot 검증을 통과한다.
USER 1000
EXPOSE 3000
CMD ["node", "server.js"]
