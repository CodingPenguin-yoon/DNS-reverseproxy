# DNS Reverse Proxy

`lab-edge` VM에서 내부 DNS와 Reverse Proxy를 관리하기 위한 홈랩 Edge Controller 프로젝트다.

현재 구현 범위는 **FastAPI + PostgreSQL + Jinja2/HTMX 기반 Edge Controller MVP**다. Proxy Routes를 PostgreSQL에 저장하고, enabled 상태인 라우트를 기준으로 Caddy `routes.caddy` 파일을 생성한 뒤 validate/apply/rollback 흐름을 수행한다.

## Documents

- [Edge Controller design](docs/edge-controller-design.md)
- [Edge Controller implementation guide](docs/edge-controller-implementation-guide.md)

## Architecture

```text
Client
  ↓
Technitium DNS
  ↓
Caddy Reverse Proxy
  ↓
Internal Service
```

```text
lab-edge VM
├── technitium
├── caddy
├── postgres
└── edge-controller
```

운영 원칙은 다음과 같다.

```text
PostgreSQL = 관리 데이터의 원천
generated/routes.caddy = Caddy 런타임 산출물
Edge Controller = 검증, 렌더링, 적용 담당
Caddy = 실제 트래픽 처리
Technitium = 실제 DNS 처리
```

Edge Controller나 PostgreSQL이 중단되어도 이미 적용된 Caddy 프록시는 계속 동작한다.

## Implemented MVP

```text
FastAPI 앱
PostgreSQL 연결
SQLAlchemy 2.x 모델
Alembic 마이그레이션
Proxy Routes CRUD API
Jinja2/HTMX 기반 웹 UI
DNS Records 상태 화면
routes.caddy 렌더러
Caddy validate/apply/rollback 서비스
Dockerfile
docker-compose.yml
```

주요 경로는 다음과 같다.

```text
edge_controller/
  main.py
  models.py
  schemas.py
  routers/
  services/
  templates/
  static/

alembic/
  versions/0001_initial.py

caddy/conf/
  Caddyfile
  generated/routes.caddy
  backups/
```

## Setup

1. 환경 파일을 만든다.

```bash
cp .env.example .env
```

2. `.env`에서 최소한 `POSTGRES_PASSWORD`를 변경한다.

```text
POSTGRES_PASSWORD=change-me
```

`edge-controller` 컨테이너는 Compose 내부 네트워크에서 `postgres:5432`로 DB에 접근한다. `DATABASE_URL`은 `docker-compose.yml`에서 다음 형태로 자동 생성된다.

```text
postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
```

3. 컨테이너를 실행한다.

```bash
docker compose up -d --build
```

`edge-controller` 컨테이너는 시작 시 자동으로 마이그레이션을 실행한다.

```text
alembic upgrade head
```

4. DNS가 준비되어 있다면 브라우저에서 접속한다.

```text
http://edge.home.arpa
```

아직 클라이언트 DNS가 준비되지 않았다면 VM에서 Host 헤더로 확인할 수 있다.

```bash
curl -H 'Host: edge.home.arpa' http://127.0.0.1/
```

## Caddy Config Flow

기본 `Caddyfile`은 고정 파일이다.

```caddy
{
    admin 0.0.0.0:2019
}

http://edge.home.arpa {
    reverse_proxy edge-controller:8000
}

import /etc/caddy/generated/routes.caddy
```

Edge Controller는 다음 파일만 생성한다.

```text
caddy/conf/generated/routes.caddy
```

Apply 흐름은 다음과 같다.

```text
1. PostgreSQL에서 enabled=true 라우트 조회
2. routes.caddy.candidate 생성
3. caddy validate 실행
4. 기존 routes.caddy 백업
5. candidate를 routes.caddy로 교체
6. 전체 Caddyfile validate
7. caddy reload --address caddy:2019 실행
8. 실패 시 이전 routes.caddy로 rollback
```

Docker socket은 Edge Controller에 마운트하지 않는다. 대신 Edge Controller 이미지 안에 Caddy 바이너리를 포함하고, Caddy admin API는 Docker 네트워크 내부에서만 사용한다.

## Web UI

화면은 두 탭으로 구성된다.

```text
Proxy Routes
DNS Records
```

Proxy Routes 화면:

```text
Route 추가
Route 수정
Route 삭제
Enabled 토글
Validate
Apply
Rollback
Config revisions 조회
```

DNS Records 화면:

```text
Zone: home.arpa
Mode: Wildcard
Wildcard: *.home.arpa -> 192.168.2.10
Technitium 상태 표시
```

초기 MVP에서는 Technitium API를 통한 DNS 레코드 CRUD는 구현하지 않았다.

## API

Health:

```text
GET    /health
```

Proxy Routes:

```text
GET    /api/proxy-routes
POST   /api/proxy-routes
PUT    /api/proxy-routes/{id}
DELETE /api/proxy-routes/{id}
```

Config:

```text
POST   /api/config/render
POST   /api/config/validate
POST   /api/config/apply
POST   /api/config/rollback/{revision_id}
GET    /api/system/status
GET    /api/config/revisions
```

예시:

```bash
curl -X POST http://edge.home.arpa/api/proxy-routes \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "heimdall",
    "domain": "heimdall.home.arpa",
    "target_scheme": "http",
    "target_host": "192.168.2.117",
    "target_port": 8080,
    "tls_insecure_skip_verify": false,
    "enabled": true
  }'
```

## Local Validation

현재 작업에서 실행한 검증은 다음과 같다.

```bash
python3 -m unittest tests.test_caddy_renderer
```

결과:

```text
Ran 3 tests
OK
```

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/dns-proxy-pycache python3 -m compileall edge_controller tests
```

결과:

```text
Python source compilation succeeded.
```

```bash
docker compose config
```

결과:

```text
Compose file parsed successfully.
```

```bash
docker compose build edge-controller
```

결과:

```text
03_dns_proxy-edge-controller  Built
```

```bash
docker compose run --rm --no-deps edge-controller python -c "from edge_controller.main import app; print(app.title)"
```

결과:

```text
Edge Controller
```

```bash
docker compose run --rm --no-deps edge-controller caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

결과:

```text
Valid configuration
```

초기 `compileall` 실행은 macOS Python의 기본 캐시 경로가 샌드박스 밖이라 실패했다. 캐시 경로를 `/private/tmp`로 지정해 다시 실행했고 통과했다.

## Remaining Operational Notes

```text
Technitium에는 별도로 *.home.arpa -> 192.168.2.10 와일드카드 레코드를 설정해야 한다.
systemd-resolved가 53번 포트를 점유하면 DNSStubListener=no 설정이 필요하다.
관리 UI 인증은 아직 구현하지 않았다.
Technitium API 기반 DNS CRUD는 다음 단계로 남겨두었다.
실제 VM에서는 docker compose up 이후 웹 UI에서 Validate/Apply를 실행해 Caddy reload까지 확인해야 한다.
```
