package com.example.mob.data.repository

import android.app.Activity
import android.content.Context
import com.example.mob.data.health.SamsungHealthManager

class HealthRepository(context: Context) {

    private val samsungHealthManager = SamsungHealthManager(context)

    val permissions = samsungHealthManager.permissions

    suspend fun connect() = samsungHealthManager.connect()

    suspend fun hasAllPermissions(): Boolean = samsungHealthManager.hasAllPermissions()

    suspend fun requestPermissions(activity: Activity) = samsungHealthManager.requestPermissions(activity)

    suspend fun syncToServer(): Result<Unit> = runCatching {
        samsungHealthManager.connect()
        samsungHealthManager.readLast24Hours()
    }
}
