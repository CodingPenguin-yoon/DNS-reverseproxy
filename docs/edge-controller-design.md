# Edge Controller 설계 문서

## 1. 목적

`lab-edge` VM은 홈랩 내부 서비스의 진입점 역할을 한다.

현재 목표는 다음 두 가지를 웹에서 쉽게 관리할 수 있는 작은 관리 도구를 만드는 것이다.

```text
1. DNS Records
2. Proxy Routes
```

초기 MVP에서는 DNS는 `*.home.arpa -> 192.168.2.10` 와일드카드 레코드를 사용하고, Edge Controller는 Caddy 리버스 프록시 설정 관리를 우선 담당한다.

## 2. 핵심 원칙

```text
PostgreSQL = 관리 데이터의 원천
Edge Controller = 검증, 렌더링, 적용 담당
Caddy 설정 파일 = 런타임 산출물
Caddy = 실제 HTTP/HTTPS 트래픽 처리
Technitium = 실제 DNS 처리
```

가장 중요한 운영 원칙은 다음과 같다.

```text
Edge Controller나 PostgreSQL이 중단되어도
이미 적용된 DNS와 Reverse Proxy는 계속 동작해야 한다.
```

따라서 Edge Controller는 Caddy의 실행 경로에 직접 끼어들지 않는다. 사용자가 설정을 변경할 때만 Caddy 설정 파일을 생성하고, 검증한 뒤 reload한다.

## 3. 전체 구성

```text
lab-edge VM
├── technitium-dns
│   ├── DNS Server
│   └── Web UI
│
├── caddy
│   └── Reverse Proxy
│
├── postgres
│   └── Edge Controller DB
│
└── edge-controller
    ├── FastAPI
    ├── Server-rendered Web UI
    ├── SQLAlchemy
    ├── Alembic
    ├── Caddy config renderer
    └── Caddy apply manager
```

추천 기술 스택은 다음과 같다.

```text
Backend: FastAPI
UI: Jinja2 + HTMX
DB: PostgreSQL
ORM: SQLAlchemy 2.x
Migration: Alembic
Proxy: Caddy
DNS: Technitium DNS Server
```

내부망 관리 도구이므로 초기에는 React 기반 SPA보다 서버 렌더링 UI가 더 단순하고 운영하기 쉽다.

## 4. 화면 구조

화면은 2개 탭으로 구성한다.

```text
[ Proxy Routes ] [ DNS Records ]                 Status: Applied
```

별도 대시보드 페이지는 만들지 않는다. 대신 모든 화면 상단에 공통 상태 영역을 둔다.

```text
현재 적용 상태
미적용 변경 여부
마지막 적용 시간
Validate 버튼
Apply 버튼
Rollback 버튼
```

### 4.1 Proxy Routes 화면

Proxy Routes 화면은 메인 작업 화면이다.

표시는 다음 형태를 기준으로 한다.

```text
Domain                 Target                         TLS   Enabled   Status
dns.home.arpa          http://technitium:5380          -     ON        Applied
heimdall.home.arpa     http://192.168.2.117:8080       -     ON        Applied
proxmox.home.arpa      https://192.168.2.100:8006      Skip  ON        Applied
```

지원 기능은 다음과 같다.

```text
프록시 라우트 추가
프록시 라우트 수정
프록시 라우트 삭제
활성/비활성 토글
설정 검증
설정 적용
이전 설정으로 롤백
```

라우트 입력 필드는 다음과 같다.

```text
Name
Domain
Target Scheme: http 또는 https
Target Host
Target Port
TLS Insecure Skip Verify
Enabled
```

### 4.2 DNS Records 화면

초기 DNS 화면은 실제 레코드 CRUD보다 상태 확인에 집중한다.

MVP 기준 화면은 다음 정보를 보여준다.

```text
Zone: home.arpa
Mode: Wildcard
Wildcard: *.home.arpa -> 192.168.2.10
Technitium: Connected / Not configured
```

향후 Technitium API를 붙이면 다음 기능으로 확장한다.

```text
A record 추가
CNAME record 추가
TTL 수정
레코드 삭제
Technitium API sync
```

## 5. Caddy 설정 관리 방식

Edge Controller가 메인 `Caddyfile` 전체를 매번 덮어쓰는 방식은 피한다.

대신 고정 base config와 자동 생성 routes config를 분리한다.

```text
caddy/conf/
├── Caddyfile
├── generated/
│   └── routes.caddy
└── backups/
    └── routes.20260615-120000.caddy
```

기본 `Caddyfile` 예시는 다음과 같다.

```caddy
http://edge.home.arpa {
    reverse_proxy edge-controller:8000
}

import /etc/caddy/generated/routes.caddy
```

Edge Controller는 `generated/routes.caddy`만 생성한다. 이렇게 하면 관리자 UI 자체 라우트가 깨질 위험을 줄일 수 있다.

## 6. Proxy Route 렌더링 예시

DB에 다음 라우트가 저장되어 있다고 가정한다.

```text
domain: heimdall.home.arpa
target_scheme: http
target_host: 192.168.2.117
target_port: 8080
tls_insecure_skip_verify: false
enabled: true
```

생성되는 Caddy 설정은 다음과 같다.

```caddy
http://heimdall.home.arpa {
    reverse_proxy 192.168.2.117:8080
}
```

HTTPS upstream이고 내부 인증서 검증을 건너뛰어야 하는 경우는 다음과 같이 생성한다.

```caddy
http://proxmox.home.arpa {
    reverse_proxy https://192.168.2.100:8006 {
        transport http {
            tls_insecure_skip_verify
        }
    }
}
```

## 7. 설정 적용 흐름

사용자가 웹에서 설정을 변경하면 다음 순서로 동작한다.

```text
1. 사용자가 Proxy Route를 추가, 수정, 삭제한다.

2. Edge Controller가 PostgreSQL에 desired state를 저장한다.

3. 사용자가 Apply를 실행한다.

4. Edge Controller가 enabled=true인 라우트를 조회한다.

5. routes.caddy.candidate 파일을 생성한다.

6. Caddy 설정 검증을 수행한다.

7. 검증 성공 시 기존 routes.caddy를 백업한다.

8. candidate 파일을 routes.caddy로 교체한다.

9. Caddy reload를 실행한다.

10. reload 성공 시 config_revisions에 applied 기록을 남긴다.

11. 실패 시 이전 routes.caddy로 rollback하고 다시 reload한다.
```

컨테이너 재시작보다 Caddy reload를 기본으로 사용한다.

```text
restart = 컨테이너 재시작
reload = Caddy 프로세스는 유지하고 설정만 반영
```

## 8. 데이터베이스 모델 초안

### 8.1 proxy_routes

```text
id
name
domain
target_scheme
target_host
target_port
tls_insecure_skip_verify
enabled
created_at
updated_at
```

권장 제약 조건은 다음과 같다.

```text
name unique
domain unique
target_scheme in ('http', 'https')
target_port between 1 and 65535
```

### 8.2 dns_records

```text
id
name
fqdn
record_type
value
ttl
enabled
sync_status
created_at
updated_at
```

MVP에서는 실제 Technitium 반영 없이 상태 표시 또는 미래 확장용으로만 사용한다.

### 8.3 config_revisions

```text
id
revision_no
rendered_config
checksum
status
message
created_at
applied_at
```

예상 status 값은 다음과 같다.

```text
rendered
validated
applied
failed
rolled_back
```

### 8.4 audit_logs

```text
id
action
target_type
target_id
status
message
created_at
```

관리 화면에서 누가 어떤 변경을 했는지 최소한의 추적을 남기기 위한 테이블이다.

## 9. API 구조

초기 API는 다음 정도로 잡는다.

```text
GET    /health

GET    /api/proxy-routes
POST   /api/proxy-routes
PUT    /api/proxy-routes/{id}
DELETE /api/proxy-routes/{id}

GET    /api/dns-records
POST   /api/dns-records
PUT    /api/dns-records/{id}
DELETE /api/dns-records/{id}

POST   /api/config/render
POST   /api/config/validate
POST   /api/config/apply
POST   /api/config/rollback/{revision_id}

GET    /api/system/status
GET    /api/config/revisions
```

UI는 Jinja2 템플릿으로 렌더링하고, 표 갱신이나 폼 제출은 HTMX로 부분 업데이트한다.

## 10. Docker Compose 관점

예상 컨테이너 구성은 다음과 같다.

```text
services:
  technitium:
    ports:
      - "53:53/tcp"
      - "53:53/udp"
      - "5380:5380/tcp"

  caddy:
    ports:
      - "80:80/tcp"
      - "443:443/tcp"
      - "443:443/udp"
    volumes:
      - ./caddy/conf/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./caddy/conf/generated:/etc/caddy/generated
      - ./caddy/data:/data
      - ./caddy/config:/config

  postgres:
    volumes:
      - ./postgres/data:/var/lib/postgresql/data

  edge-controller:
    volumes:
      - ./caddy/conf/generated:/app/caddy/generated
      - ./caddy/conf/backups:/app/caddy/backups
```

Caddy reload 실행 방식은 구현 단계에서 선택한다.

권장 후보는 다음 두 가지다.

```text
1. Caddy Admin API 사용
2. 제한된 권한의 helper 명령으로 docker exec caddy caddy reload 실행
```

Docker socket 전체를 Edge Controller에 마운트하는 방식은 권한이 너무 크므로 기본안으로 두지 않는다.

## 11. 보안 원칙

관리 UI는 내부망에서만 접근 가능해야 한다.

초기 보안 기준은 다음과 같다.

```text
관리 UI는 home.arpa 내부 도메인에서만 노출
관리자 인증 사용
민감 정보는 .env에 저장
PostgreSQL은 외부 포트로 직접 노출하지 않음
Edge Controller는 Caddy 설정 변경 전 항상 validate 수행
Docker socket 직접 마운트는 피함
```

초기 인증 방식은 단일 관리자 계정 또는 Basic Auth로 충분하다. 이후 필요하면 세션 로그인 방식으로 확장한다.

## 12. MVP 범위

첫 버전의 범위는 다음과 같다.

```text
PostgreSQL 연결
Alembic migration
Proxy Routes CRUD
routes.caddy 자동 생성
Caddy validate
Caddy reload
백업 및 rollback
간단한 Web UI
DNS 화면은 wildcard 상태 표시만
```

MVP 완료 기준은 다음과 같다.

```text
웹에서 heimdall.home.arpa 라우트를 추가할 수 있다.
DB에 저장된다.
routes.caddy가 생성된다.
validate 성공 시에만 반영된다.
Caddy reload 후 실제 접속된다.
실패하면 이전 설정이 유지된다.
Edge Controller가 죽어도 기존 프록시는 계속 동작한다.
```

## 13. 단계별 로드맵

### 13.1 1단계: 수동 기반 확정

```text
Technitium DNS 동작 확인
*.home.arpa -> 192.168.2.10 와일드카드 레코드 설정
Caddy 수동 reverse_proxy 동작 확인
고정 Caddyfile + generated/routes.caddy 구조 확정
```

### 13.2 2단계: Proxy Controller MVP

```text
FastAPI 프로젝트 생성
PostgreSQL 연결
proxy_routes 모델 작성
routes.caddy 렌더러 작성
validate/apply/rollback 구현
Proxy Routes 웹 화면 구현
```

### 13.3 3단계: DNS 화면 확장

```text
Technitium API 연결 상태 확인
home.arpa zone 정보 표시
wildcard record 상태 표시
개별 DNS record 모델 정리
```

### 13.4 4단계: DNS 자동 반영

```text
A record CRUD
CNAME record CRUD
Technitium API sync
DNS 변경 이력 기록
```

### 13.5 5단계: 외부 자동화 연동

```text
Heimdall 또는 VM 생성 시스템과 연동
서비스 생성 후 DNS/Proxy 자동 등록
API token 기반 인증
작업 이력 및 실패 재시도
```

## 14. 보류 결정 사항

구현 전에 확정해야 할 항목은 다음과 같다.

```text
Caddy reload를 Admin API로 할지 helper 명령으로 할지
관리 UI 인증을 Basic Auth로 시작할지 앱 로그인으로 시작할지
DNS Records를 MVP에서 DB에 저장만 할지 완전히 제외할지
HTTPS 내부 도메인 인증서를 어떻게 처리할지
```

현재 추천은 다음과 같다.

```text
Caddy reload: Docker socket 없이 제한된 helper 방식 또는 Caddy Admin API 검토
인증: 초기 Basic Auth
DNS: MVP에서는 상태 표시만
HTTPS: 처음에는 HTTP 내부 도메인으로 시작하고 이후 내부 CA 검토
```
