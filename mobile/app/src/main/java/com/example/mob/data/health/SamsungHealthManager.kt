package com.example.mob.data.health

import android.app.Activity
import android.content.Context
import android.util.Log
import com.example.mob.data.remote.RetrofitClient
import com.samsung.android.sdk.health.data.HealthDataService
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.permission.AccessType
import com.samsung.android.sdk.health.data.permission.Permission
import com.samsung.android.sdk.health.data.request.DataType
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.LocalTimeFilter
import com.samsung.android.sdk.health.data.request.Ordering
import java.time.LocalDateTime
import java.time.ZoneId

class SamsungHealthManager(private val context: Context) {

    private var store: HealthDataStore? = null

    // 수집 가능한 모든 권한 세트
    val permissions = setOf(
        Permission.of(DataTypes.HEART_RATE, AccessType.READ),
        Permission.of(DataTypes.STEPS, AccessType.READ),
        Permission.of(DataTypes.SLEEP, AccessType.READ),
        Permission.of(DataTypes.BLOOD_OXYGEN, AccessType.READ),
        Permission.of(DataTypes.EXERCISE, AccessType.READ),
        Permission.of(DataTypes.ACTIVITY_SUMMARY, AccessType.READ),
        Permission.of(DataTypes.FLOORS_CLIMBED, AccessType.READ),
        Permission.of(DataTypes.BODY_COMPOSITION, AccessType.READ),
        Permission.of(DataTypes.WATER_INTAKE, AccessType.READ),
        Permission.of(DataTypes.BLOOD_PRESSURE, AccessType.READ),
        Permission.of(DataTypes.BLOOD_GLUCOSE, AccessType.READ),
        Permission.of(DataTypes.USER_PROFILE, AccessType.READ),
        Permission.of(DataTypes.ENERGY_SCORE, AccessType.READ)
    )

    suspend fun connect() {
        Log.d("SamsungHealth", "HealthDataStore 연결 중...")
        store = HealthDataService.getStore(context)
    }

    suspend fun hasAllPermissions(): Boolean {
        val currentStore = store ?: return false
        val granted = currentStore.getGrantedPermissions(permissions)
        return granted.containsAll(permissions)
    }

    suspend fun requestPermissions(activity: Activity): Set<Permission> {
        val currentStore = store ?: return emptySet()
        return currentStore.requestPermissions(permissions, activity)
    }

    suspend fun readLast24Hours(): WatchHealthSnapshot {
        Log.d("SamsungHealth", "전체 건강 데이터 수집 시작...")
        val currentStore = store ?: error("Samsung Health에 연결되지 않음")
        val endTime = LocalDateTime.now()
        val startTime = endTime.minusHours(24)
        val timeFilter = LocalTimeFilter.of(startTime, endTime)
        val zone = ZoneId.systemDefault()

        // 1. 심박수 (최신)
        val heartRate = currentStore.readData(
            DataTypes.HEART_RATE.readDataRequestBuilder
                .setLocalTimeFilter(timeFilter).setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()?.getValue(DataType.HeartRateType.HEART_RATE)?.toInt()

        // 2. 걸음 수 (합계)
        val steps = currentStore.aggregateData(
            DataType.StepsType.TOTAL.requestBuilder.setLocalTimeFilter(timeFilter).build()
        ).dataList.firstOrNull()?.value?.toInt()

        // 3. 활동 요약 (칼로리, 거리 등)
        val totalCalories = currentStore.aggregateData(DataType.ActivitySummaryType.TOTAL_CALORIES_BURNED.requestBuilder.setLocalTimeFilter(timeFilter).build()).dataList.firstOrNull()?.value?.toDouble()
        val activeCalories = currentStore.aggregateData(DataType.ActivitySummaryType.TOTAL_ACTIVE_CALORIES_BURNED.requestBuilder.setLocalTimeFilter(timeFilter).build()).dataList.firstOrNull()?.value?.toDouble()
        val distance = currentStore.aggregateData(DataType.ActivitySummaryType.TOTAL_DISTANCE.requestBuilder.setLocalTimeFilter(timeFilter).build()).dataList.firstOrNull()?.value?.toDouble()
        val activeTime = currentStore.aggregateData(DataType.ActivitySummaryType.TOTAL_ACTIVE_TIME.requestBuilder.setLocalTimeFilter(timeFilter).build()).dataList.firstOrNull()?.value?.toMinutes()?.toInt()

        // 4. 층수 (합계)
        val floors = currentStore.aggregateData(
            DataType.FloorsClimbedType.TOTAL.requestBuilder.setLocalTimeFilter(timeFilter).build()
        ).dataList.firstOrNull()?.value?.toInt()

        // 5. 수면 (최신 세션)
        val sleepPoint = currentStore.readData(
            DataTypes.SLEEP.readDataRequestBuilder
                .setLocalTimeFilter(timeFilter).setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()
        val sleepDuration = sleepPoint?.getValue(DataType.SleepType.DURATION)
        val sleepScore = sleepPoint?.getValue(DataType.SleepType.SLEEP_SCORE)
        val latestSleepSession = sleepPoint?.getValue(DataType.SleepType.SESSIONS)?.lastOrNull()

        // 6. 체성분 (최신)
        val bodyComp = currentStore.readData(
            DataTypes.BODY_COMPOSITION.readDataRequestBuilder.setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()
        val weight = bodyComp?.getValue(DataType.BodyCompositionType.WEIGHT)?.toDouble()
        val bodyFat = bodyComp?.getValue(DataType.BodyCompositionType.BODY_FAT)?.toDouble()
        val skeletalMuscle = bodyComp?.getValue(DataType.BodyCompositionType.SKELETAL_MUSCLE)?.toDouble()

        // 7. 유저 프로필
        val profile = currentStore.readData(DataTypes.USER_PROFILE.readDataRequestBuilder.build()).dataList.firstOrNull()
        val height = profile?.getValue(DataType.UserProfileDataType.HEIGHT)?.toDouble()

        // 8. 음수량
        val waterIntake = currentStore.aggregateData(
            DataType.WaterIntakeType.TOTAL.requestBuilder.setLocalTimeFilter(timeFilter).build()
        ).dataList.firstOrNull()?.value?.toDouble()

        // 9. 혈중 산소
        val spO2 = currentStore.readData(
            DataTypes.BLOOD_OXYGEN.readDataRequestBuilder
                .setLocalTimeFilter(timeFilter).setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()?.getValue(DataType.BloodOxygenType.OXYGEN_SATURATION)?.toDouble()

        // 10. 에너지 점수 (최신)
        val energyScore = currentStore.readData(
            DataTypes.ENERGY_SCORE.readDataRequestBuilder.setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()?.getValue(DataType.EnergyScoreType.ENERGY_SCORE)?.toInt()

        // 11. 혈압
        val bp = currentStore.readData(
            DataTypes.BLOOD_PRESSURE.readDataRequestBuilder.setLocalTimeFilter(timeFilter).setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()
        val systolic = bp?.getValue(DataType.BloodPressureType.SYSTOLIC)?.toDouble()
        val diastolic = bp?.getValue(DataType.BloodPressureType.DIASTOLIC)?.toDouble()

        // 12. 혈당
        val glucose = currentStore.readData(
            DataTypes.BLOOD_GLUCOSE.readDataRequestBuilder.setLocalTimeFilter(timeFilter).setOrdering(Ordering.DESC).build()
        ).dataList.firstOrNull()?.getValue(DataType.BloodGlucoseType.GLUCOSE_LEVEL)?.toDouble()

        val snapshot = WatchHealthSnapshot(
            measuredAt = endTime,
            heartRate = heartRate,
            steps = steps,
            floors = floors,
            caloriesBurned = totalCalories,
            activeCalories = activeCalories,
            distance = distance,
            activeTimeMinutes = activeTime,
            sleepDurationMinutes = sleepDuration?.toMinutes()?.toInt(),
            sleepStartAt = latestSleepSession?.startTime?.let { LocalDateTime.ofInstant(it, zone) },
            sleepEndAt = latestSleepSession?.endTime?.let { LocalDateTime.ofInstant(it, zone) },
            sleepScore = sleepScore,
            spO2 = spO2,
            bodyWeight = weight,
            bodyHeight = height,
            bodyFat = bodyFat,
            skeletalMuscle = skeletalMuscle,
            waterIntake = waterIntake,
            energyScore = energyScore,
            bloodPressureSystolic = systolic,
            bloodPressureDiastolic = diastolic,
            bloodGlucose = glucose
        )

        Log.d("SamsungHealth", """
            ===== [ALL DATA] 갤럭시워치 수집 결과 =====
            심박수: ${snapshot.heartRate} | 걸음수: ${snapshot.steps} | 층수: ${snapshot.floors}
            에너지점수: ${snapshot.energyScore} | 활동시간: ${snapshot.activeTimeMinutes}분
            칼로리(총/활동): ${snapshot.caloriesBurned}/${snapshot.activeCalories} kcal
            수면효율: ${snapshot.sleepScore}점 | 수면시간: ${snapshot.sleepDurationMinutes}분
            체지방: ${snapshot.bodyFat}% | 근육량: ${snapshot.skeletalMuscle}kg
            혈압: ${snapshot.bloodPressureSystolic}/${snapshot.bloodPressureDiastolic} | 혈당: ${snapshot.bloodGlucose}
            ===========================================
        """.trimIndent())


        sendDataToServer(snapshot)

        return snapshot
    }

    private suspend fun sendDataToServer(snapshot: WatchHealthSnapshot) {
        try {
            val request = SamsungHealthRequest(
                heartRate = snapshot.heartRate,
                steps = snapshot.steps,
                floors = snapshot.floors,
                energyScore = snapshot.energyScore,
                activeTimeMinutes = snapshot.activeTimeMinutes,
                caloriesBurned = snapshot.caloriesBurned,
                activeCalories = snapshot.activeCalories,
                sleepScore = snapshot.sleepScore,
                sleepDurationMinutes = snapshot.sleepDurationMinutes,
                bodyFat = snapshot.bodyFat,
                skeletalMuscle = snapshot.skeletalMuscle,
                bloodPressureSystolic = snapshot.bloodPressureSystolic,
                bloodPressureDiastolic = snapshot.bloodPressureDiastolic,
                bloodGlucose = snapshot.bloodGlucose
            )

            val response = RetrofitClient.healthApiService.sendSamsungHealthData(request)
            if (response.status == 200) {
                Log.d("SamsungHealth", "서버 전송 성공: ${response.message}")
            } else {
                Log.e("SamsungHealth", "서버 전송 실패: ${response.message}")
            }
        } catch (e: Exception) {
            Log.e("SamsungHealth", "서버 전송 중 오류 발생", e)
        }
    }

}
