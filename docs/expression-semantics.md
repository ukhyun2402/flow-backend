# Flow 1.0 Python 실행 의미

- `ref`와 `op/args`는 선언형 표현식이며 임의 Python 코드를 실행하지 않는다. 일반 객체와 배열은 재귀 매핑한다. `ref/op`를 실제 업무 값으로 전달하려면 `literal`로 감싼다.
- 참조 영역은 input, nodes.<id>.output, context.requestId/startedAt이다. 없는 참조는 검증 오류이며 null과 다르다. `coalesce`는 null만 건너뛴다.
- args는 왼쪽부터 모두 평가한다. and/or/coalesce의 단락 평가는 없다. 암묵적 문자열·숫자·boolean 변환은 금지한다.
- 비교·논리·null·사칙연산·concat/trim/contains·toNumber/toString/toDateTime을 지원한다. 깊이 64, 전체 표현식 평가 10000회로 제한한다.
- 숫자는 Decimal을 사용한다. 나눗셈은 DECIMAL128(정밀도 34, HALF_EVEN), 다른 연산은 최대 정밀도 512로 제한한다. 수치 문자열은 256자, scale 절댓값은 1000 이내이다.
- 소수는 `{type: decimal, value: 문자열}`, JSON 안전 범위 밖의 정수는 `{type: integer, value: 문자열}`로 전달한다. 입력·출력 계약은 해당 형태를 선언한다.
- 날짜 변환은 offset이 있는 ISO-8601을 받아 UTC로 정규화한다. DB 시간대는 어댑터 세션 설정과 실제 DB 검증 대상이다. timezone 없는 DB datetime은 UTC 세션 정책으로 해석한다.
- 일반 노드는 success/error, 분기는 true/false/error이다. 선택한 경로만 실행하며 실패한 노드의 출력은 생성하지 않는다. 정상 종료는 response.http이다.
- 같은 트랜잭션 내의 DB 노드는 같은 연결을 사용한다. 다른 DB·외부 HTTP·중첩 트랜잭션은 검증에서 차단한다. 미처리 오류는 활성 트랜잭션 롤백을 시도한다.
- 미리보기의 commit은 rollback으로 처리한다. 실제 생성 서버에서는 commit한다. 트랜잭션 밖의 변경 미리보기는 각 노드 종료 시 롤백한다.
- 외부 HTTP는 별도 서비스 허용 목록에 선언된 주소만 사용하며 redirect를 따라가지 않는다. 외부 응답은 1MB로 제한한다.
