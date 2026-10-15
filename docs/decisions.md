# 0.2 설계 결정 · 2026-10-15

- 원본 SPEC.md의 노드 의미·Flow JSON 1.0·검증·비밀정보 정책을 유지한다. 실행 언어는 사용자 요청에 따라 Python 3.12+ / FastAPI로 변경한다.
- 실행 엔진은 UI에 의존하지 않는다. React는 화면 구성에 사용하며 React Flow 의존성은 제거했다. draw.io v32.4.1 공식 WAR를 SHA-256으로 확인해 로컬 정적 자산으로 제공한다.
- draw.io는 동일 origin iframe에서 JSON postMessage 프로토콜을 사용한다. origin과 source를 모두 확인한다. 기본 동작에 외부 편집 서비스가 필요하지 않다.
- XML의 object.flowType / flowConfig가 실행 노드의 의미를 보존한다. 라벨·위치·스타일은 실행 타입을 바꾸지 않는다. 알 수 없는 일반 도형과 여러 페이지는 명시적으로 거절한다.
- DB와 프로젝트는 다대다이다. 프로젝트는 기준 DB를 갖고 추가 DB를 연결한다. DB 선택은 그 DB에 연결된 프로젝트를 필터링한다.
- 프로젝트 → 업무 단위 → 프로세스는 포함 관계이다. 프로세스 ID는 업무 단위 내에서 고유하며 내부 UUID는 별도로 유지한다. DB 선택을 바꿔도 같은 공유 프로젝트를 복제하지 않는다.
- Flow의 DB 자원은 프로젝트 연결 DB의 부분집합이어야 한다. SQL 노드가 실행 DB를 선택하며 단일 프로세스의 다중 DB 순차 실행을 허용한다. 분산 트랜잭션은 MVP 제외를 유지한다.
- 관리 저장소는 SQLite WAL이다. 초안은 expectedVersion으로 비교 갱신하고, 확정 버전은 새 revision으로만 추가한다. 원본 Java 데이터·코드는 legacy와 기존 data 파일에 보존하며 자동 변환·삭제하지 않는다.
- Python DB-API 차이는 Databases에 모은다. Oracle은 python-oracledb, MySQL은 PyMySQL, Tibero는 pyodbc/ODBC이다. SQL AST 검증과 이름 바인딩을 분리한다.
- MySQL 조회는 streaming cursor와 서버 LIMIT, Oracle/Tibero 조회는 ROWNUM 제한을 적용한다. 행·바이트·시간 제한과 취소는 각 실제 드라이버 환경에서 추가 검증한다.
- 생성기는 공통 엔진 소스를 그대로 포함한 독립 Python 프로젝트를 만든다. 관리 API·저장소·draw.io·UI XML을 제외하고 고정 ZIP 시간·정렬된 경로·파일 해시를 사용한다.
- 프로젝트 전체 생성에서는 모든 프로세스의 API 라우트 충돌을 검사한다. 생성 시 미저장된 다른 프로세스 탭의 변경은 포함하지 않는다.
- 비밀정보는 환경 변수 참조로만 해석한다. 생성 서버에는 별도의 FLOW_RUNTIME_TOKEN을 사용한다. 초기 DB 항목은 연결 미설정 예시이다.
