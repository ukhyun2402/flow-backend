# DB 지원 검증 현황

| DB | 연결 방식 | 드라이버 | 실제 DB 검증 |
|---|---|---|---|
| MySQL | JDBC | Maven 의존성 mysql-connector-j | 미실행: 서버·계정 미제공 |
| Oracle | JDBC | Maven 의존성 ojdbc11 | 미실행: 서버·계정 미제공 |
| Tibero | JDBC | 운영자가 제공하는 vendor JAR | 미실행: 드라이버·서버·계정 미제공 |
| H2 | JDBC | 테스트 전용 | 바인딩·조회 제한·변경·롤백 자동 테스트 |

H2 결과로 위 3개 DB 지원 완료를 주장하지 않는다. 지원 DB 버전, 드라이버 버전, OS/CPU, JDK, 라이선스는 실환경 검사 후 이 표에 기록한다.

DB별 수용 테스트: 연결, 메타데이터, 이름 바인딩, NULL/정밀 숫자/날짜, 행·바이트 제한, SQL 오류, 변경과 롤백, 격리 수준, 긴 SQL 시간 제한, Statement.cancel, 취소 후 풀 연결 재사용, TLS, 컨테이너 배포.

Tibero JDBC 재배포 권한을 확인한 뒤 `drivers/`에 배치하고 다음처럼 외부 클래스를 로드한다:

```
java -Dloader.path=drivers -cp target/flow-platform-0.1.0.jar org.springframework.boot.loader.launch.PropertiesLauncher
```

기본 Dockerfile에는 Tibero JAR가 포함되지 않는다. 위 실행 방식과 별도 드라이버 마운트를 적용한 이미지를 검증해야 한다.
