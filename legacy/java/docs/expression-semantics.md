# Flow 1.0 실행 의미

표현식은 `{ "ref": "input.name" }`, `{ "op": "concat", "args": [...] }` 형태이다. 일반 객체·배열은 재귀적으로 매핑한다. `ref`, `op` 자체를 업무 데이터로 전달하려면 `{ "literal": ... }`로 감싼다. 임의 코드·스크립트는 실행하지 않는다.

- 없는 참조는 `VALIDATION_ERROR`이며 null과 다르다. `coalesce`는 null만 건너뛰며 없는 참조를 복구하지 않는다.
- 비교·계산·논리·문자열 연산에는 암묵적 타입 변환이 없다. 숫자로 바꾸려면 `toNumber`, 문자열은 `toString`을 사용한다.
- `and`, `or`, `coalesce`를 포함해 args는 왼쪽부터 모두 평가한다. 단락 평가는 없다.
- `eq`, `ne`는 숫자에는 수치 비교를, 나머지는 JSON 값 비교를 사용한다. `gt/gte/lt/lte`는 숫자 전용이다.
- `not/isNull/notNull/trim/toNumber/toString/toDateTime`은 인자 1개, 비교·사칙연산·contains는 2개이다. `and/or`는 1개 이상이다. `concat`과 `coalesce`는 가변 인자이다.
- 깊이 64, 실행 전체 평가 노드 10,000개로 제한한다. 수치 문자열은 256자·정밀도 256, 계산 결과 정밀도 512, scale 절댓값 1000 이내이다.
- 숫자는 BigDecimal로 계산한다. 나눗셈은 DECIMAL128(유효숫자 34, HALF_EVEN)을 사용한다. 0으로 나누기는 검증 오류이다.
- 안전 정수 범위 이내의 정수 결과는 JSON 숫자이다. 범위를 초과하면 `{ "type": "integer", "value": "9007199254740993" }`, 소수 계산 결과는 `{ "type": "decimal", "value": "0.3" }`이다. 타입 정보가 있는 숫자는 계산·SQL 바인딩에서도 사용할 수 있다. 요청·응답 스키마는 해당 표현 형태를 선언해야 한다.
- `toDateTime`은 명시적 offset이 있는 ISO-8601 문자열만 허용하고 UTC Instant 문자열로 반환한다. SQL DATE는 날짜, TIME은 시간, TIMESTAMP는 JDBC가 해석한 Instant로 반환한다. DB 세션의 시간대 설정은 지원 매트릭스 검증 대상이다.
- trim은 Java String.trim과 같은 U+0000~U+0020 양끝 제거이다. null을 문자열이나 숫자로 자동 변환하지 않는다.

Flow는 단일 경로만 실행한다. 성공한 노드만 `nodes.<id>.output`에 출력을 만든다. 오류 연결선에서는 실패한 노드 출력이 존재하지 않는다. 정상 종료는 response.http, 처리되지 않은 오류는 공통 오류 응답이며 활성 트랜잭션을 정리한다.

변경 미리보기에서 transaction.commit 노드는 실제로 rollback을 실행한다. 실제 실행에서는 commit을 수행한다. http.call은 트랜잭션 내부에 둘 수 없다. DB 작업의 출력 계약이 있으면 노드 성공 전에 검사한다.
