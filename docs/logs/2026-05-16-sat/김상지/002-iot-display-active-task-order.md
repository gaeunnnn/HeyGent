# IoT display active task 요청 순서 보존

## 날짜

2026-05-16

## 작성자

김상지

## 대상 브랜치

- `AI-fix/memory-writeback-target-conflict4`

## 작업 배경

이번 브랜치에는 장기기억 안정화 외에 IoT display active task 조회 순서 보존 변경도 포함되어 있다.

Redis repository에서 active task 목록을 조회할 때 요청 순서와 반환 순서가 달라질 수 있어, 상위 로직이 기대한 task 순서와 실제 display 상태 매핑이 어긋날 수 있었다.

## 작업 내용

- Redis에서 active task state를 조회한 뒤 입력 task id 순서를 보존하도록 정렬 로직을 보강했다.
- 순서 보존 동작을 검증하는 repository 테스트를 추가했다.

## 주요 커밋

```text
78b36328 BE-fix : IoT display active task 요청 순서 보존
```

## 주요 파일

- `backend/src/main/java/com/ssafy/heygent/domain/iot/repository/DeviceDisplayStateRedisRepository.java`
- `backend/src/test/java/com/ssafy/heygent/domain/iot/repository/DeviceDisplayStateRedisRepositoryTest.java`

## 검증

```powershell
.\gradlew.bat test --tests "com.ssafy.heygent.domain.iot.repository.DeviceDisplayStateRedisRepositoryTest"
```

결과: 통과
