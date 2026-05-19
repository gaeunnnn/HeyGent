# syntax=docker/dockerfile:1.6

# 로컬 개발용 Vite dev 서버 컨테이너.
# 운영용 정적 빌드 + nginx 흐름은 별도 Dockerfile로 분리한다.

FROM node:20-alpine

WORKDIR /app

# 1) 의존성 메타데이터(lock 파일)를 먼저 복사한다.
#    package.json / package-lock.json 이 안 바뀌면 다음 RUN 단계가 캐시되어 재실행되지 않는다.
COPY package.json package-lock.json ./

# 2) 의존성 설치는 BuildKit cache mount 로 npm 다운로드 캐시(/root/.npm)를 재사용한다.
#    package-lock.json 이 package.json 과 어긋날 수 있어 npm install 로 자동 동기화한다.
RUN --mount=type=cache,target=/root/.npm \
    npm install

# 3) 소스 복사. dev 모드에서는 compose volume 마운트로 핫 리로드를 활용한다.
COPY . .

EXPOSE 5173

# Vite dev 서버를 IPv4 + IPv6 dual-stack 으로 바인딩한다.
# vite.config.ts 의 server.host: true 가 이를 처리하므로 CLI 에서 --host 0.0.0.0 을 주지 않는다.
# (--host 0.0.0.0 은 IPv4 만 listen 해서 Windows 호스트의 localhost(::1) 가 connection refused 가 된다.)
CMD ["npm", "run", "dev", "--", "--port", "5173"]
