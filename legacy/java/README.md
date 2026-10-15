# Flow Studio

Flow로 HTTP API를 설계하고 독립 Java 서버 프로젝트를 생성하는 로컬 개발 도구입니다. 원본 기획서는 [SPEC.md](SPEC.md), 결정 사항은 [docs/decisions.md](docs/decisions.md)에 있습니다.

현재 상태: **실행 가능한 초기 구현**. 편집 → 검증 → 미리보기 → ZIP 생성 → 별도 Maven 빌드 → 생성 API 실행을 검증했습니다. 기획서 전체의 완료 선언은 아닙니다. 실제 Tibero·Oracle·MySQL 수용 테스트는 접속 환경이 필요합니다.

## 빠른 실행 (Windows PowerShell 7)

필수: JDK 17 이상, Node.js 22.12 이상. 권장 실행 JDK는 21입니다. 현재 머신에서는 Android Studio의 JBR 25로 빌드·테스트했습니다.

```powershell
# Maven이 없는 경우 프로젝트 내부에 설치
.\scripts\bootstrap.ps1

# JAVA_HOME이 설정되어 있지 않은 현재 머신의 예
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'

npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
& .\.tools\apache-maven-3.9.11\bin\mvn.cmd '-Dmaven.repo.local=.tools/repository' package
.\scripts\run.ps1
```

[http://127.0.0.1:8080](http://127.0.0.1:8080)을 열고 실행 터미널의 개발 토큰을 우측 상단에 입력합니다. 기본 예제는 DB가 필요 없는 인사 API입니다. **미리보기**로 실행 경로와 응답을 보고 **서버 생성**으로 ZIP을 내려받습니다. 동일 버전은 덮어쓸 수 없으므로 저장된 Flow를 수정한 뒤에는 JSON 패널에서 **다음 버전 만들기**를 사용합니다.

노드 설정을 편집한 뒤 **설정 적용**을 눌러 반영합니다. SQL 패널은 현재 편집 중인 SQL을 실행하며, 바인딩 테스트 값은 별도 JSON 입력란에 입력합니다. 인증 토큰은 브라우저 저장소에 저장하지 않습니다.

## 개발 및 검증

```powershell
# 프런트 개발 서버 (백엔드는 별도 실행)
npm.cmd --prefix frontend run dev

# Java 단위/통합 테스트
& .\.tools\apache-maven-3.9.11\bin\mvn.cmd '-Dmaven.repo.local=.tools/repository' test

# 패키징 후, 관리 서버와 생성 서버를 별도 프로세스로 기동하는 수용 테스트
.\scripts\smoke.ps1 -JavaHome $env:JAVA_HOME
```

`smoke.ps1`은 18080·18081 포트를 사용하고 시작한 프로세스를 종료합니다. 결과물과 로그는 `.tools/smoke-<id>/`에 남깁니다. 의존성 다운로드 외에 외부 서비스가 필요하지 않습니다.

## DB·외부 서비스 설정

```powershell
$env:FLOW_DATABASE_CONFIG = (Resolve-Path config/databases.example.json).Path
$env:MAIN_DB_PASSWORD = 'your-local-db-password'
$env:FLOW_SERVICE_CONFIG = (Resolve-Path config/services.example.json).Path
$env:SERVICE_API_TOKEN = 'your-local-service-token'
.\scripts\run.ps1
```

예시 파일을 복사해 실제 환경의 주소·계정을 설정하세요. 비밀번호는 JSON이 아닌 환경 변수로 제공합니다. 조회에는 읽기 전용 DB 계정을 사용하세요. SQL 파서만으로 저장 함수의 부작용을 판정하지 않습니다. 변경 미리보기는 `environment: development|test` 및 `rollbackSafetyVerified: true`가 모두 필요하며, 운영자가 테이블 엔진·트리거 등 부작용을 먼저 확인해야 합니다.

[DB 지원 매트릭스](docs/support-matrix.md)에 드라이버와 실환경 검증 항목을 기록했습니다. Tibero JAR는 제공받은 후 재배포 조건을 확인해 별도 로딩해야 합니다. H2는 자동 테스트에만 포함되며 제품의 지원 DB 목록을 대체하지 않습니다.

## 권한

길이 24자 이상의 토큰을 환경 변수로 제공합니다. 미설정 토큰은 허용하지 않습니다.

| 환경 변수 | 권한 |
|---|---|
| FLOW_ADMIN_TOKEN | Flow 저장·실행·SQL·연결 확인·서버 생성 |
| FLOW_EDITOR_TOKEN | Flow 조회·저장·검증 |
| FLOW_RUNNER_TOKEN | Flow 조회·검증·미리보기·SQL 미리보기·취소 |

관리 API 요청에는 `Authorization: Bearer <token>`이 필요합니다. 관리 서버는 기본적으로 localhost에 바인딩합니다. 현재 권한은 역할별 공유 개발 토큰이며 사용자 계정·SSO는 후속 범위입니다. 생성 서버는 별도 `FLOW_RUNTIME_TOKEN`을 사용합니다. 공개 API는 `settings.authentication: public`을 명시적으로 저장한 경우에만 생성합니다.

## 주요 API

| 메서드·경로 | 기능 |
|---|---|
| POST /api/validate | Flow 명세·경로·참조·타입·트랜잭션 검사 |
| GET /api/flows | 저장된 Flow 버전 목록 |
| POST /api/flows | 불변 버전 저장 |
| GET /api/flows/{id}/{revision} | 특정 버전 복원 |
| POST /api/preview | `{flow,input,executionId?}` 실행 |
| POST /api/generate | Flow → 독립 서버 ZIP |
| POST /api/databases/{id}/test | 연결 확인 |
| GET /api/databases/{id}/metadata | 테이블·컬럼 탐색 |
| POST /api/sql/preview | `{databaseRef,sql,parameters,command,executionId?}` |
| POST /api/executions/{id}/cancel | 실행 중 JDBC Statement 취소 요청 |
| GET /api/executions/{id} | 보관된 미리보기 실행 추적 |
| GET /api/history | 최근 저장·실행·생성 감사 이벤트 |

실행 ID는 클라이언트가 생성한 UUID를 지정할 수 있습니다. SQL 취소는 드라이버의 `Statement.cancel`에 의존하며 각 DB에서 실제 취소와 연결 회복을 검증해야 합니다. 노드 사이 구간 및 외부 HTTP 호출의 사용자 취소는 후속 작업입니다. 시간 제한은 각 작업 및 Flow의 deadline으로 적용합니다.

## 생성 서버

ZIP을 새 디렉터리에 풀고 생성된 README를 따릅니다. `mvn package` 후 `java -jar target/flow-platform-0.1.0.jar`로 실행합니다. 원본 관리 서버, 프런트엔드, Node.js는 생성 서버 실행에 필요하지 않습니다. API 라우팅, 공통 엔진, JDBC 어댑터, Flow, JSON Schema, OpenAPI, Dockerfile, 해시 manifest가 포함됩니다. SQL 편집·관리 API는 포함하지 않습니다.

ZIP 생성은 같은 Flow·생성기·런타임에서 바이트 단위로 재현되며 UI 위치 변경은 결과에 영향을 주지 않습니다. 생성물은 디스크에 직접 덮어쓰지 않으므로 새 디렉터리에 내보내고 `extensions/` 사용자 코드는 별도로 유지하세요.

## 구현 경계

- 현재 파일 저장소는 단일 로컬 프로세스용입니다. PostgreSQL 저장소 및 다중 인스턴스 잠금은 미구현입니다.
- 정적 타입 검사는 명시된 계약과 추론 가능한 표현식에 적용됩니다. SQL 결과의 완전한 정적 타입 검증에는 노드 `config.outputSchema`를 명시해야 합니다. 실행 시 입력·응답 계약도 검증합니다.
- LOB·바이너리 결과 미리보기는 제한하며 DB별 전체 타입 매핑은 실환경 확인이 필요합니다.
- 노드 설정 UI는 JSON 편집 중심입니다. 스키마 기반 폼, SQL 자동완성·DB 오류 위치 강조, 결과 컬럼→출력 계약 자동 매핑은 후속 작업입니다.
- 감사·실행 추적은 입력·출력 원문을 기록하지 않고 파일당 10MB에서 1회전 보관합니다. 생성 서버는 동일 추적 메타데이터를 구조화한 JSON 로그로 출력하며 영구 수집기 연동은 후속 작업입니다.
- Docker 정의를 제공하지만 현재 머신에 Docker가 없어 컨테이너 기동은 검증하지 못했습니다.

구체적인 수용 기준별 상태는 [docs/acceptance.md](docs/acceptance.md)를 참고하세요.
