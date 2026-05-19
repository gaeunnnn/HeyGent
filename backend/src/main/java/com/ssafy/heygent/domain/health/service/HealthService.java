package com.ssafy.heygent.domain.health.service;

import com.ssafy.heygent.domain.health.dto.request.SamsungHealthRequestDto;
import com.ssafy.heygent.domain.health.dto.response.HealthSummaryResponseDto;
import com.ssafy.heygent.domain.health.entity.*;
import com.ssafy.heygent.domain.health.repository.MeasurementLogRepository;
import com.ssafy.heygent.domain.user.entity.User;
import com.ssafy.heygent.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class HealthService {

    private final UserRepository userRepository;
    private final MeasurementLogRepository logRepository;

    @Transactional
    public void processHealthData(Long userId, SamsungHealthRequestDto dto) {
        // 1. 사용자 조회 (실존 여부 확인)
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 사용자입니다."));

        // 2. 중심이 되는 MeasurementLog 생성 (Category는 'ALL' 또는 상황에 맞춰 지정)
        MeasurementLog mainLog = MeasurementLog.builder()
                .user(user)
                .measuredAt(LocalDateTime.now())
                .category(LogCategory.ALL) // 필요 시 Enum에 ALL 추가
                .build();

        DailyActivity activity = DailyActivity.builder()
                .measurementLog(mainLog)
                .stepCount(dto.getSteps() != null ? dto.getSteps().intValue() : null)
                .activeMinutes(dto.getActiveTimeMinutes())
                .totalCalories(dto.getCaloriesBurned())
                .activeCalories(dto.getActiveCalories())
                .build();

        PhysicalProfile profile = PhysicalProfile.builder()
                .measurementLog(mainLog)
                .bodyFatPct(dto.getBodyFat())
                .muscleMassKg(dto.getSkeletalMuscle())
                .build();

        VitalLog vital = VitalLog.builder()
                .measurementLog(mainLog)
                .heartRateBpm(dto.getHeartRate())
                .systolicBp(dto.getBloodPressureSystolic())
                .diastolicBp(dto.getBloodPressureDiastolic())
                .build();

        SleepRecord sleep = SleepRecord.builder()
                .measurementLog(mainLog)
                .durationMinutes(dto.getSleepDurationMinutes())
                .sleepScore(dto.getSleepScore())
                .build();

        mainLog.setDetails(activity, profile, vital, sleep);

        logRepository.save(mainLog);
    }

    @Transactional(readOnly = true)
    public Optional<HealthSummaryResponseDto> getLatestHealthData(Long userId) {
        return logRepository.findTopByUser_IdOrderByMeasuredAtDesc(userId)
                .map(HealthSummaryResponseDto::from);
    }
}