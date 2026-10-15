# 백엔드 서버 자동 생성 프로그램 기획서

문서 버전: 0.1  
문서 목적: AI 기반 설계·구현·검증의 입력 명세  
요구 수준: MUST = 필수, SHOULD = 권장, MAY = 선택  
미확정 사항: 본 문서의 기본값을 적용하되 구현 전에 변경 가능

## 1. 제품 정의

업무 프로세스를 Flow로 작성하고, 해당 Flow를 실행 가능한 백엔드 서버로 변환하는 프로그램.

사용자는 시각적 편집기에서 API 입력, 데이터 검증, 조건 분기, SQL 실행, 외부 API 호출, 응답 반환을 연결한다. 프로그램은 Flow를 표준 중간 표현으로 저장하고, 검증·미리보기·서버 생성을 제공한다.

핵심 산출물:

- 시각적 Flow 편집기
- 플랫폼 독립 Flow 명세
- Flow 검증기
- Flow 실행 엔진
- SQL 편집 및 결과 미리보기
- 실행 가능한 백엔드 프로젝트 생성기
- 생성 서버의 API 문서와 실행 추적 정보

## 2. 목표 및 범위

### 2.1 필수 목표

| ID | 요구사항 |
|---|---|
| REQ-001 | 노드와 연결선을 이용하여 업무 프로세스를 작성한다. |
| REQ-002 | 노드 종류별로 고유한 시각 형태와 실행 의미를 정의한다. |
| REQ-003 | UI 라이브러리와 실행 플랫폼에 종속되지 않는 Flow 명세를 사용한다. |
| REQ-004 | Tibero, Oracle, MySQL을 지원한다. |
| REQ-005 | SQL 입력·수정·파라미터 설정·결과 미리보기를 제공한다. |
| REQ-006 | Flow에서 실행 가능한 백엔드 서버 프로젝트를 생성한다. |
| REQ-007 | 입력·출력·분기·오류 처리·트랜잭션 규칙을 검증한다. |
| REQ-008 | 실행 결과를 원본 Flow의 노드와 연결하여 추적한다. |

### 2.2 MVP 범위

- HTTP/JSON 기반 동기식 API
- 순차 실행 및 조건 분기
- 단일 DB 연결 내 트랜잭션
- SQL 조회 및 변경
- 외부 HTTP API 호출
- 단일 런타임용 서버 생성
- 로컬 실행 및 컨테이너 실행 지원
- Flow 버전 관리 및 생성 이력

### 2.3 MVP 제외

- 임의 반복문 및 순환 연결
- 병렬 분기 및 합류
- 여러 DB에 걸친 분산 트랜잭션
- 장기 실행 워크플로 및 재시작 시 실행 복구
- 사용자 임의 코드 실행
- 생성 코드의 변경 내용을 Flow로 역변환
- 모든 SQL 방언의 자동 변환
- 여러 언어용 서버 동시 생성

플랫폼 독립성은 표준 명세와 런타임 어댑터로 확보한다. MVP에서 모든 플랫폼용 실행기를 구현할 필요는 없다.

## 3. 기본 설계 결정

| 항목 | 기본값 |
|---|---|
| 편집기 | 웹 애플리케이션 |
| Flow UI | React Flow 또는 Svelte Flow를 교체 가능한 UI 계층으로 사용 |
| 원본 저장 형식 | 버전이 명시된 JSON |
| 데이터 계약 | JSON Schema |
| 생성 API 문서 | OpenAPI |
| API 프로토콜 | HTTP/JSON |
| MVP 실행 구조 | 공통 실행 엔진 + Flow 명세 + DB 어댑터 |
| 서버 생성 방식 | 실행 엔진을 포함한 독립 서버 프로젝트 생성 |
| 실행 순서 | 제어 연결선으로 결정 |
| 값 전달 | 명시적 변수 참조 및 입력 매핑 |
| 표현식 | 제한된 선언형 표현식 |
| 비밀정보 | 외부 Secret 참조 |
| 코드 생성 재현성 | 동일 명세·생성기 버전·설정에서 동일 결과 |

DB 지원과 배포 환경을 우선 검증한 후 첫 실행 런타임을 확정한다. 편집기 기술과 실행 런타임 기술은 서로 독립적으로 선택한다.

## 4. 시스템 구조

```text
Flow Editor
    ↓
Canonical Flow JSON
    ↓
Schema Validator + Semantic Validator
    ↓
Normalized Execution Plan
    ├─ Preview Runner
    └─ Server Generator
           ↓
       Generated Server
           ├─ HTTP Adapter
           ├─ Flow Runtime
           ├─ Database Adapters
           ├─ Secret Provider
           └─ Execution Trace
```

구성요소 책임:

| 구성요소 | 책임 |
|---|---|
| Flow Editor | 노드 배치, 연결, 속성 편집, 오류 표시 |
| Flow Repository | Flow·버전·환경 설정·생성 이력 저장 |
| Validator | 구조, 타입, 연결, 응답, 트랜잭션 검증 |
| Execution Planner | Flow를 검증된 실행 계획으로 변환 |
| Preview Runner | 테스트 입력으로 실행 및 노드별 결과 표시 |
| SQL Service | 연결 확인, SQL 실행, 결과 제한, 취소 |
| Database Adapter | DB별 연결·바인딩·타입·트랜잭션 차이 처리 |
| Server Generator | 실행 가능한 프로젝트 및 배포 파일 생성 |
| Flow Runtime | 실행 계획에 따라 노드 실행 |
| Trace Service | 실행 상태, 소요 시간, 오류 기록 |

편집기의 내부 노드 형식을 원본 Flow 명세로 사용해서는 안 된다.

## 5. Flow 구성요소

모든 노드는 `id`, `type`, `name`, `config`를 갖는다. 실행 의미는 노드의 형태가 아닌 `type`과 `config`로 결정한다.

색상은 보조 표시이며, 형태·아이콘·텍스트를 함께 사용한다.

| type | 표시 이름 | 고유 형태 | 실행 의미 |
|---|---|---|---|
| `trigger.http` | HTTP 진입 | 캡슐 | HTTP 요청을 입력 계약에 맞춰 수신 |
| `validate` | 입력 검증 | 방패형 오각형 | 스키마 및 업무 검증 |
| `transform` | 데이터 변환 | 평행사변형 | 값 매핑, 구조 변환, 계산 |
| `branch` | 조건 분기 | 마름모 | 조건 결과에 따라 한 경로 선택 |
| `db.query` | SQL 조회 | 원통 | 조회 SQL 실행 |
| `db.command` | SQL 변경 | 원통 + 변경 아이콘 | INSERT·UPDATE·DELETE 실행 |
| `http.call` | 외부 API 호출 | 육각형 | 외부 HTTP 요청 실행 |
| `transaction.begin` | 트랜잭션 시작 | 아래로 열린 괄호형 | 지정 DB 트랜잭션 시작 |
| `transaction.commit` | 트랜잭션 확정 | 닫힌 괄호형 + 체크 | 트랜잭션 커밋 |
| `transaction.rollback` | 트랜잭션 취소 | 닫힌 괄호형 + 취소 | 트랜잭션 롤백 |
| `error.raise` | 업무 오류 | 팔각형 | 명시적 오류 발생 |
| `response.http` | HTTP 응답 | 종단 캡슐 + 응답 아이콘 | 상태 코드·헤더·본문 반환 |

### 5.1 연결선

- 제어 연결선만 실행 순서를 결정한다.
- 일반 노드는 `success`, `error` 출력 포트를 갖는다.
- `branch`는 `true`, `false`, `error` 출력 포트를 갖는다.
- 각 출력 포트는 최대 하나의 다음 노드와 연결한다.
- 응답 노드는 다음 노드와 연결할 수 없다.
- 데이터 의존성은 입력 매핑으로 선언하며 실행 경로상의 참조 유효성을 검증한다.
- 여러 경로가 같은 노드로 연결될 수 있으나, 한 실행에서는 선택된 한 경로만 진입한다.

### 5.2 실행 규칙

- Flow당 HTTP 진입 노드는 정확히 하나다.
- 순환 연결은 MVP에서 금지한다.
- 분기는 반드시 한 경로만 선택한다.
- 정상 종료 경로는 HTTP 응답으로 끝나야 한다.
- 처리되지 않은 오류는 공통 오류 응답으로 종료한다.
- 오류 연결선이 있으면 해당 경로로 이동한다.
- 오류 연결선이 없으면 활성 트랜잭션을 롤백하고 종료한다.
- 명시적 롤백은 데이터를 취소하며, 다음 연결선이 있으면 실행을 계속한다.
- 실행 경로에서 생성되지 않은 노드 출력 참조는 금지한다.
- 노드 ID는 위치 변경 및 이름 변경과 무관하게 유지한다.

## 6. 표준 Flow 명세

### 6.1 필수 필드

| 필드 | 의미 |
|---|---|
| `specVersion` | Flow 명세 버전 |
| `id` | Flow 고유 ID |
| `revision` | 저장 버전 |
| `name` | Flow 이름 |
| `inputSchema` | 요청 데이터 계약 |
| `outputSchema` | 정상 응답 데이터 계약 |
| `resources` | DB·외부 서비스 논리 참조 |
| `nodes` | 실행 노드 |
| `edges` | 제어 연결 |
| `settings` | 시간 제한·오류 응답 정책 |
| `ui` | 위치·크기 등 실행과 무관한 정보 |

예시:

```json
{
  "specVersion": "1.0",
  "id": "get-user",
  "revision": 1,
  "name": "사용자 조회",
  "inputSchema": {
    "type": "object",
    "properties": {
      "userId": { "type": "integer" }
    },
    "required": ["userId"],
    "additionalProperties": false
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "id": { "type": "integer" },
      "name": { "type": "string" }
    },
    "required": ["id", "name"]
  },
  "resources": {
    "databases": ["main"]
  },
  "nodes": [
    {
      "id": "start",
      "type": "trigger.http",
      "name": "조회 요청",
      "config": {
        "method": "GET",
        "path": "/users/{userId}",
        "input": {
          "userId": {
            "source": "path.userId",
            "convert": "integer"
          }
        }
      }
    },
    {
      "id": "query",
      "type": "db.query",
      "name": "사용자 조회",
      "config": {
        "databaseRef": "main",
        "sql": "SELECT id, name FROM users WHERE id = :userId",
        "parameters": {
          "userId": {
            "ref": "input.userId"
          }
        },
        "resultMode": "zeroOrOne"
      }
    },
    {
      "id": "found",
      "type": "branch",
      "name": "사용자 존재",
      "config": {
        "condition": {
          "op": "notNull",
          "args": [
            { "ref": "nodes.query.output.row" }
          ]
        }
      }
    },
    {
      "id": "ok",
      "type": "response.http",
      "name": "정상 응답",
      "config": {
        "status": 200,
        "body": {
          "ref": "nodes.query.output.row"
        }
      }
    },
    {
      "id": "missing",
      "type": "error.raise",
      "name": "사용자 없음",
      "config": {
        "code": "USER_NOT_FOUND",
        "status": 404,
        "message": "사용자를 찾을 수 없습니다."
      }
    }
  ],
  "edges": [
    { "from": "start", "port": "success", "to": "query" },
    { "from": "query", "port": "success", "to": "found" },
    { "from": "found", "port": "true", "to": "ok" },
    { "from": "found", "port": "false", "to": "missing" }
  ],
  "settings": {
    "timeoutMs": 10000
  },
  "ui": {}
}
```

### 6.2 플랫폼 독립 계약

- 저장 형식과 실행 의미를 별도 명세로 정의한다.
- 표준 표현식의 연산·타입 변환·null 처리 규칙을 고정한다.
- 런타임별로 동일 적합성 테스트를 실행한다.
- 지원되지 않는 명세 버전이나 노드 종류는 생성 전에 오류로 반환한다.
- SQL 본문은 지정 DB의 방언을 사용한다.
- Flow 이식성과 SQL 이식성은 별개다.
- DB를 변경하면 SQL 호환성을 다시 검증한다.

## 7. 데이터 및 표현식

참조 영역:

```text
input.*                 정규화된 요청 입력
nodes.<nodeId>.output.*  이전 노드 출력
context.requestId       요청 추적 ID
context.startedAt       실행 시작 시간
```

표현식은 문자열 기반 임의 코드 대신 선언형 구조를 사용한다.

지원 연산:

- 비교: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`
- 논리: `and`, `or`, `not`
- null: `isNull`, `notNull`, `coalesce`
- 계산: `add`, `subtract`, `multiply`, `divide`
- 문자열: `concat`, `trim`, `contains`
- 변환: 명시적 숫자·문자열·날짜 변환

규칙:

- 암묵적 타입 변환을 금지한다.
- null과 미정의 값의 처리 규칙을 구분한다.
- 정밀 소수 및 JSON 안전 범위를 초과하는 정수는 타입 정보와 문자열 값으로 전달한다.
- 날짜·시간은 명시된 형식과 시간대 정책을 따른다.
- 파일 시스템·네트워크·프로세스 접근은 표현식에서 금지한다.
- 표현식 깊이 및 연산 횟수를 제한한다.

## 8. DB 지원

### 8.1 연결 설정

```text
id
vendor: tibero | oracle | mysql
host
port
database / serviceName / SID
username
passwordSecretRef
tls
connectionTimeoutMs
queryTimeoutMs
poolSettings
```

비밀번호는 Flow 및 생성 코드에 저장하지 않는다. 환경별 연결 설정은 논리 ID에 매핑한다.

지원 대상 DB 버전, 드라이버 버전, 실행 환경, 배포 라이선스는 구현 착수 단계에서 지원 매트릭스로 확정한다. 연결 성공만으로 해당 DB의 전체 지원을 판정하지 않는다.

### 8.2 어댑터 계약

```text
testConnection(config)
getMetadata(connection)
executeQuery(connection, sql, parameters, options)
executeCommand(connection, sql, parameters, options)
beginTransaction(connection, options)
commit(transaction)
rollback(transaction)
cancel(executionId)
normalizeError(error)
```

어댑터는 다음 차이를 처리한다.

- 연결 및 인증
- 파라미터 바인딩
- 메타데이터 조회
- 결과 타입
- 조회 결과 제한
- 트랜잭션 및 격리 수준
- 시간 제한 및 취소
- DB 오류 정규화

Tibero 지원은 Oracle과 별도로 검증한다.

## 9. SQL 편집 및 미리보기

### 9.1 편집 기능

- SQL 입력·수정·저장
- 선택 DB에 맞는 구문 강조
- 테이블·컬럼 탐색
- 파라미터 이름·타입·테스트 값 설정
- 결과 컬럼과 출력 계약 연결
- 오류 위치 및 DB 오류 표시
- DB 변경 시 호환성 재검증 표시

### 9.2 SQL 실행 규칙

- 값은 바인딩 파라미터로 전달한다.
- 입력값의 SQL 문자열 직접 삽입을 금지한다.
- 테이블·컬럼 등 식별자 변경은 허용 목록 기반 설정으로 제한한다.
- MVP에서는 노드당 단일 SQL 문만 허용한다.
- DDL, 관리 명령, 저장 프로시저 호출은 MVP에서 제외한다.
- SELECT로 시작한다는 이유만으로 안전한 조회로 판정하지 않는다.
- 실제 권한 제한은 DB 계정의 권한으로 적용한다.

### 9.3 조회 미리보기

기본값:

```text
maxRows = 100
maxResponseBytes = 5 MB
timeoutMs = 10000
```

표시 항목:

- 컬럼명·타입·null 허용 정보
- 반환된 행
- 조회 소요 시간
- 결과 잘림 여부
- 오류 정보

제한값 초과 시 전체 결과를 계속 수집하지 않는다. DB별 제한 방식과 드라이버 제한을 함께 적용한다.

### 9.4 변경 미리보기

- 개발·테스트 DB에서만 허용한다.
- 별도 트랜잭션으로 실행하고 종료 시 롤백한다.
- 실제 커밋 기능은 미리보기와 별도 동작으로 제공한다.
- 변경 행 수와 지원 가능한 반환값을 표시한다.
- 연결을 잃어 롤백 결과를 확인할 수 없으면 성공으로 표시하지 않는다.
- 비트랜잭션 테이블, 외부 부작용이 있는 트리거 등 롤백으로 복구할 수 없는 대상은 미리보기를 차단한다.
- 부작용 검증에는 테스트 DB를 사용하며, 롤백만으로 원상 복구를 보장하지 않는다.

## 10. 트랜잭션

- 한 트랜잭션은 한 DB 연결에 종속된다.
- 트랜잭션 내부 DB 노드는 같은 연결을 사용한다.
- 중첩 트랜잭션은 MVP에서 금지한다.
- 모든 경로에서 commit 또는 rollback 여부를 검증한다.
- 활성 트랜잭션 상태에서 HTTP 응답을 반환할 수 없다.
- 처리되지 않은 오류 및 요청 취소 시 롤백을 시도한다.
- 트랜잭션 내부 외부 HTTP 호출은 MVP에서 금지한다.
- DB별 지원되지 않는 격리 수준은 설정 단계에서 차단한다.

## 11. 검증 및 오류 모델

생성 전 검증 항목:

- 필수 필드 및 명세 버전
- 노드 ID 중복
- 진입 노드 개수
- 존재하지 않는 노드 참조
- 잘못된 포트 및 연결 개수
- 도달할 수 없는 노드
- 순환 연결
- 분기 경로 누락
- 정상 경로의 응답 누락
- 입력·출력 타입 불일치
- 경로상 보장되지 않는 출력 참조
- DB 및 Secret 참조 누락
- SQL 파라미터 누락
- 트랜잭션 범위 위반
- API 경로 및 메서드 충돌

검증 오류 형식:

```json
{
  "code": "FLOW_INVALID_REFERENCE",
  "flowId": "get-user",
  "nodeId": "ok",
  "field": "config.body",
  "message": "현재 실행 경로에서 보장되지 않는 출력을 참조합니다."
}
```

실행 오류 분류:

```text
VALIDATION_ERROR
BUSINESS_ERROR
DB_ERROR
EXTERNAL_API_ERROR
TIMEOUT
CANCELLED
INTERNAL_ERROR
```

외부 응답에는 비밀번호, SQL 파라미터 원문, 내부 스택을 포함하지 않는다.

## 12. 서버 생성

입력:

- 검증된 Flow 버전
- 생성기 및 런타임 버전
- 대상 런타임 설정
- DB 드라이버 구성
- 환경 변수 및 Secret 참조 명세

출력:

```text
generated-server/
  src/
  flows/
  schemas/
  config/
  tests/
  openapi.json
  Dockerfile
  .env.example
  dependency-manifest
  generation-manifest.json
  README.md
```

`generation-manifest.json`에는 Flow 버전·해시, 생성기 버전, 런타임 버전, 의존성 정보를 기록한다.

생성 규칙:

- 생성 결과만으로 독립 실행 가능해야 한다.
- 프로젝트에는 API 라우팅, 실행 엔진, DB 어댑터 구성이 포함된다.
- 생성 코드와 사용자 확장 코드를 별도 경로로 분리한다.
- 재생성으로 사용자 확장 코드를 덮어쓰지 않는다.
- 생성 코드 직접 수정은 Flow로 역반영하지 않는다.
- 생성물에 비밀정보 및 미리보기 데이터가 포함되어서는 안 된다.
- 생성 서버에는 SQL 편집·미리보기 관리 API를 포함하지 않는다.

## 13. 편집 화면

| 영역 | 기능 |
|---|---|
| 프로젝트 목록 | Flow·버전·생성 이력 |
| 노드 팔레트 | 노드 종류 및 검색 |
| Flow 캔버스 | 배치·연결·확대·축소·오류 표시 |
| 속성 패널 | 입력 매핑·노드 설정 |
| SQL 패널 | 편집·파라미터·결과 미리보기 |
| 검증 패널 | 오류 위치로 이동 |
| 실행 패널 | 테스트 입력·경로·노드별 결과 |
| 생성 패널 | 대상 환경·생성 결과·실행 안내 |

편집기는 저장·불러오기·실행 취소·다시 실행을 지원한다.

## 14. 실행 추적 및 접근 제어

실행 추적:

```text
executionId
flowId
flowRevision
nodeId
status
startedAt
durationMs
errorCode
```

- 캔버스에서 실행 경로 및 실패 노드를 표시한다.
- 입력·출력 원문 기록은 기본 비활성화한다.
- 민감 필드 마스킹 및 기록 용량 제한을 적용한다.
- SQL 변경 실행, DB 연결 수정, 서버 생성 권한을 구분한다.
- 편집·SQL 실행·생성 이벤트의 감사 이력을 저장한다.
- 생성 API의 인증 정책은 명시적 설정으로 제공한다.
- 인증 없이 공개 실행하는 설정은 사용자가 명시적으로 선택해야 한다.

## 15. 수용 기준

| ID | 완료 조건 |
|---|---|
| AC-001 | 요청→검증→SQL 조회→분기→응답 Flow를 편집·저장·복원할 수 있다. |
| AC-002 | UI 위치 변경으로 실행 명세의 의미가 변경되지 않는다. |
| AC-003 | 각 노드 종류를 형태·아이콘·이름으로 구별할 수 있다. |
| AC-004 | Tibero·Oracle·MySQL 각각에서 연결·조회·변경·롤백·오류 처리를 검증한다. |
| AC-005 | SQL 값 파라미터를 문자열 조합 없이 바인딩한다. |
| AC-006 | 조회 미리보기의 행·바이트·시간 제한이 실제로 적용된다. |
| AC-007 | 변경 미리보기 후 허용된 트랜잭션 대상 데이터가 유지된다. |
| AC-008 | 잘못된 연결·타입·출력 참조·트랜잭션 범위를 생성 전에 차단한다. |
| AC-009 | 생성 프로젝트를 독립 실행하여 정의된 API 응답을 얻는다. |
| AC-010 | 오류 발생 노드와 Flow 버전을 실행 기록에서 확인할 수 있다. |
| AC-011 | 생성물 및 로그에 비밀정보가 노출되지 않는다. |
| AC-012 | 동일 입력 조건으로 서버를 재생성하면 동일 산출물을 얻는다. |
| AC-013 | 런타임 적합성 테스트에서 분기·타입·null·오류 의미가 명세와 일치한다. |

## 16. 구현 순서

1. Flow JSON Schema, 노드 계약, 표현식 의미, 적합성 테스트 정의
2. DB별 드라이버·배포 가능성 및 지원 매트릭스 검증
3. Flow 검증기 및 실행 계획 생성기 구현
4. 최소 실행 엔진과 DB 어댑터 구현
5. SQL 편집·미리보기 구현
6. Flow 편집기와 검증 오류 연동
7. 서버 생성 및 독립 실행 검증
8. 실행 추적·권한·버전 관리 적용

AI 구현 지침:

- 본 문서의 MUST 요구사항과 수용 기준을 구현 완료 판단 기준으로 사용한다.
- 미확정 사항은 구현 전에 결정 기록으로 남긴다.
- UI 전용 데이터와 실행 데이터를 분리한다.
- DB별 차이는 어댑터에 모은다.
- 표현식 평가에 임의 코드 실행 기능을 사용하지 않는다.
- 실제 DB 통합 검증 없이 해당 DB 지원을 완료로 판정하지 않는다.
- 플랫폼 독립성을 위해 실행 의미를 명시하며, 런타임의 암묵적 동작에 의존하지 않는다.