package com.ssafy.heygent.domain.health.dto.request;

import lombok.*;

@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SamsungHealthRequestDto {
    private Integer heartRate;
    private Long steps;
    private Integer floors;
    private Integer energyScore;
    private Integer activeTimeMinutes;
    private Double caloriesBurned;
    private Double activeCalories;
    private Integer sleepScore;
    private Integer sleepDurationMinutes;
    private Double bodyFat;
    private Double skeletalMuscle;
    private Double bloodPressureSystolic;
    private Double bloodPressureDiastolic;
    private Double bloodGlucose;
}