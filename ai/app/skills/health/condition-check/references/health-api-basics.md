# 헬스 API 기본 사용법

## 도구

`health.execute` 를 사용한다.

```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/api/v1/health/me/latest"
    }
  ]
}
```

## 규칙

- endpoint는 반드시 `/api/v1/health/` 로 시작해야 한다.
- `userId`, `user_id`, token, credential을 넣지 않는다. 런타임이 인증된 사용자 식별자를 자동으로 바인딩한다.
- 현재 1차 지원 endpoint는 `GET /api/v1/health/me/latest` 이다.
- `data` 가 없거나 필드가 `null` 이면 0으로 취급하지 말고 "조회되지 않음"으로 본다.
- 사용자가 특정 기간을 물어도 현재 endpoint가 최신 요약만 지원하면, 최신 데이터 기준으로 답하고 기간 비교가 불가능하다고 밝힌다.

## 조회 가능한 데이터 필드

| 필드 | 타입 | 의미 | 답변에서의 사용 |
|---|---:|---|---|
| `step_count` | Int | 걸음 수 | 하루 활동량과 저강도 움직임 참고 |
| `active_minutes` | Int | 활성 시간 | 실제 활동 지속 시간 참고 |
| `total_calories` | Decimal | 총 칼로리 | 하루 전체 에너지 소비량 참고 |
| `active_calories` | Decimal | 활동 칼로리 | 운동·활동으로 소비한 칼로리 참고 |
| `height_cm` | Decimal | 키(cm) | 체성분 해석 보조 정보 |
| `weight_kg` | Decimal | 몸무게(kg) | 체중 변화와 체성분 맥락 참고 |
| `body_fat_pct` | Decimal | 체지방률(%) | 체성분 추세와 장기 관리 힌트 참고 |
| `muscle_mass_kg` | Decimal | 골격근량(kg) | 근육량 추세와 운동 방향 참고 |
| `heart_rate_bpm` | Int | 심박수(BPM) | 부담, 긴장, 회복 상태 참고 |
| `systolic_bp` | Decimal | 수축기 혈압 | 활력 징후 주의 신호 참고 |
| `diastolic_bp` | Decimal | 이완기 혈압 | 활력 징후 주의 신호 참고 |
| `duration_minutes` | Int | 총 수면 시간(분) | 회복 상태의 1차 참고 지표 |
| `sleep_score` | Int | 수면 점수 | 기기 기반 수면 품질 참고 지표 |

## 응답 필드 이름

backend 응답은 camelCase 필드를 사용할 수 있다. 다음처럼 대응해서 읽는다.

| 스킬 문서 필드 | API 응답 필드 |
|---|---|
| `step_count` | `stepCount` |
| `active_minutes` | `activeMinutes` |
| `total_calories` | `totalCalories` |
| `active_calories` | `activeCalories` |
| `height_cm` | `heightCm` |
| `weight_kg` | `weightKg` |
| `body_fat_pct` | `bodyFatPct` |
| `muscle_mass_kg` | `muscleMassKg` |
| `heart_rate_bpm` | `heartRateBpm` |
| `systolic_bp` | `systolicBp` |
| `diastolic_bp` | `diastolicBp` |
| `duration_minutes` | `durationMinutes` |
| `sleep_score` | `sleepScore` |
