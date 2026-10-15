# Python DB 지원 매트릭스

| 대상 | 구현 | 실제 인스턴스 검증 |
|---|---|---|
| Oracle | python-oracledb 4.0.2 Thin, 이름 바인딩, ROWNUM, call_timeout/cancel | 미실행: 접속 환경 필요 |
| MySQL | PyMySQL 1.2.3, 순서 바인딩, streaming cursor, LIMIT, 네트워크 제한, 별도 제어 연결의 KILL QUERY | 미실행: 접속 환경 필요 |
| Tibero | pyodbc 5.3.0 + vendor ODBC DSN, 순서 바인딩, ROWNUM, query timeout/cancel | 미실행: 드라이버·DSN·접속 환경 필요 |
| SQLite 테스트 브리지 | 실제 SQL, 다중 DB 읽기, 바인딩, 행·바이트 제한, 변경·롤백 | 자동 테스트 통과. 제품 DB 지원을 대체하지 않음 |

검증 환경: Windows, Python 3.12.14. 대상 DB 버전·OS/CPU·TLS·인증·드라이버 재배포 조건은 실제 배포 조합마다 확정한다. Oracle/Tibero를 같은 DB로 취급하지 않는다.

필수 검증: 연결·스키마 탐색, 정밀 숫자/NULL/날짜, 세션 시간대, SQL 방언, 조회 제한, 단일 문장 처리, 변경·롤백, 트리거/비트랜잭션 테이블, 격리 수준, 취소·시간 초과·연결 끊김 후 상태, 취소 권한, 컨테이너 의존성.

Oracle/Tibero의 LOB와 바이너리 결과는 초기 버전에서 미리보기를 차단한다. 앱의 readonly 플래그는 DB 계정 권한을 대체하지 않는다. SQL 함수의 부작용을 파서만으로 완전히 판정하지 않는다.

Tibero DSN에는 서버·포트·DB 및 필요한 TLS 설정을 구성한다. 비밀번호는 DSN 파일이나 Flow에 저장하는 대신 런타임 Secret 참조로 전달한다. 운영체제별 ODBC 드라이버 설치 및 vendor 배포 조건을 확인해야 한다.
