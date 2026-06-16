# Edge Controller 구현 지침서

이 문서는 Edge Controller MVP를 구현할 때 작업자가 따라야 할 기준을 정리한다.

상세 설계는 [Edge Controller 설계 문서](edge-controller-design.md)를 우선 기준으로 삼는다.

## 1. 작업 목표

`lab-edge` VM에서 홈랩 내부 서비스의 Reverse Proxy 설정을 웹으로 관리하는 Edge Controller MVP를 구현한다.

MVP는 Proxy Routes 관리를 우선한다. DNS Records 화면은 초기에는 `home.arpa` 와일드카드 상태 표시 수준으로 구현한다.

## 2. 핵심 원칙

```text
PostgreSQL = 관리 데이터의 원천
Caddy 설정 파일 = 런타임 산출물
Edge Controller = 데이터 검증, Caddy 설정 생성, 적용 담당
Caddy = 실제 트래픽 처리
Technitium = 실제 DNS 처리
```

구현 시 반드시 지킬 원칙은 다음과 같다.

```text
Edge Controller가 죽어도 이미 적용된 프록시는 계속 동작해야 한다.
Caddy 메인 Caddyfile 전체를 덮어쓰지 않는다.
Edge Controller는 generated/routes.caddy만 생성한다.
설정 적용 전에는 반드시 validate를 수행한다.
validate 또는 reload 실패 시 기존 설정을 유지하거나 rollback한다.
Docker socket 전체 마운트는 기본 방식으로 사용하지 않는다.
민감 정보는 .env로 분리한다.
PostgreSQL은 외부 포트로 직접 노출하지 않는 방향을 기본으로 한다.
```

## 3. 권장 기술 스택

```text
Backend: FastAPI
UI: Jinja2 + HTMX
DB: PostgreSQL
ORM: SQLAlchemy 2.x
Migration: Alembic
Proxy: Caddy
DNS: Technitium DNS Server
```

내부망 관리 도구이므로 초기 구현에서는 React 기반 SPA보다 서버 렌더링 UI를 우선한다.

## 4. 구현 범위

MVP에 포함할 항목은 다음과 같다.

```text
FastAPI 기반 Edge Controller
PostgreSQL 연결
SQLAlchemy 모델
Alembic 마이그레이션
Proxy Routes CRUD
Jinja2 + HTMX 기반 단순 웹 UI
Proxy Routes 탭
DNS Records 탭
routes.caddy 렌더러
Caddy validate/apply/rollback 흐름
Dockerfile 및 docker-compose.yml
README 실행 방법
```

MVP에서 DNS Records 탭은 다음 수준이면 충분하다.

```text
Zone: home.arpa
Mode: Wildcard
Wildcard: *.home.arpa -> 192.168.2.10
Technitium: Connected / Not configured
```

## 5. 화면 요구사항

화면은 2개 탭으로 구성한다.

```text
[ Proxy Routes ] [ DNS Records ]
```

공통 상단에는 다음 상태를 표시한다.

```text
현재 적용 상태
마지막 적용 시간
미적용 변경 여부
Validate 버튼
Apply 버튼
Rollback 버튼
```

### 5.1 Proxy Routes

목록 테이블 컬럼은 다음을 기준으로 한다.

```text
Domain
Target
TLS
Enabled
Status
Actions
```

지원 기능은 다음과 같다.

```text
추가
수정
삭제
활성/비활성 토글
```

Proxy Route 필드는 다음과 같다.

```text
name
domain
target_scheme: http 또는 https
target_host
target_port
tls_insecure_skip_verify
enabled
```

### 5.2 DNS Records

초기 DNS Records 화면은 실제 Technitium 레코드 CRUD가 아니라 상태 표시 중심으로 구현한다.

Technitium API 연동은 이후 단계에서 확장한다.

## 6. DB 모델

초기 모델은 다음 네 가지를 기준으로 한다.

```text
proxy_routes
dns_records
config_revisions
audit_logs
```

`proxy_routes`는 MVP의 핵심 모델이다.

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

## 7. Caddy 설정 생성 규칙

HTTP upstream 예시는 다음과 같다.

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

고정 Caddyfile과 생성 파일은 분리한다.

```text
caddy/conf/
├── Caddyfile
├── generated/
│   └── routes.caddy
└── backups/
    └── routes.20260615-120000.caddy
```

기본 Caddyfile은 다음 구조를 기준으로 한다.

```caddy
http://edge.home.arpa {
    reverse_proxy edge-controller:8000
}

import /etc/caddy/generated/routes.caddy
```

## 8. Apply 흐름

설정 적용은 다음 순서로 구현한다.

```text
1. 사용자가 Proxy Route를 추가, 수정, 삭제한다.
2. Edge Controller가 PostgreSQL에 desired state를 저장한다.
3. 사용자가 Apply를 실행한다.
4. enabled=true인 라우트를 조회한다.
5. routes.caddy.candidate 파일을 생성한다.
6. Caddy 설정 validate를 수행한다.
7. validate 성공 시 기존 routes.caddy를 백업한다.
8. candidate 파일을 routes.caddy로 교체한다.
9. Caddy reload를 실행한다.
10. reload 성공 시 config_revisions에 applied 기록을 남긴다.
11. 실패 시 이전 routes.caddy로 rollback하고 다시 reload한다.
```

컨테이너 restart보다 Caddy reload를 기본으로 사용한다.

## 9. 구현 순서

권장 구현 순서는 다음과 같다.

```text
1. 현재 저장소 구조 확인
2. FastAPI 프로젝트 골격 생성
3. PostgreSQL 설정 추가
4. SQLAlchemy 모델 작성
5. Alembic 마이그레이션 구성
6. Proxy Routes CRUD API 작성
7. routes.caddy 렌더러 작성
8. validate/apply/rollback 서비스 작성
9. Jinja2/HTMX 웹 화면 작성
10. Dockerfile 및 docker-compose.yml 작성
11. README 실행 방법 업데이트
12. 가능한 범위의 테스트 또는 검증 명령 실행
```

## 10. 완료 기준

MVP 완료 기준은 다음과 같다.

```text
웹에서 proxy route를 추가할 수 있다.
DB에 저장된다.
Apply 시 generated/routes.caddy가 생성된다.
validate 성공 시에만 적용된다.
reload 실패 시 rollback된다.
DNS Records 화면은 home.arpa wildcard 상태를 보여준다.
README만 보고 로컬 또는 VM 실행 흐름을 이해할 수 있다.
변경 범위와 남은 리스크가 마지막에 요약된다.
```

## 11. 하지 말아야 할 것

```text
설계와 무관한 대규모 리팩터링
Caddyfile 직접 수동 편집 방식과 DB 기반 관리 방식 혼합
검증 없이 routes.caddy 교체
Docker socket 전체 마운트 기본 채택
Technitium DNS CRUD를 MVP에 무리하게 포함
React SPA를 초기 필수 요건으로 추가
```
