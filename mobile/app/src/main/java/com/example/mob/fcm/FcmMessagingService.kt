package com.example.mob.fcm

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.mob.MainActivity
import com.example.mob.data.remote.RetrofitClient
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * FCM 메시지 수신 서비스.
 *
 * 앱이 백그라운드일 때 AI 응답이 완료되면 푸시 알림을 표시한다.
 * onNewToken: 토큰 갱신 시 AI 백엔드에 자동 재등록
 */
class FcmMessagingService : FirebaseMessagingService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** 토큰 갱신 — AI 백엔드에 새 토큰 등록 */
    override fun onNewToken(token: String) {
        Log.d("FCM", "토큰 갱신: ${token.take(20)}...")
        scope.launch {
            try {
                RetrofitClient.aiApiService.registerFcmToken(mapOf("token" to token))
                Log.d("FCM", "백엔드 토큰 등록 완료")
            } catch (e: Exception) {
                Log.w("FCM", "토큰 등록 실패: ${e.message}")
            }
        }
    }

    /** 포그라운드 메시지 수신 */
    override fun onMessageReceived(message: RemoteMessage) {
        Log.d("FCM", "FCM 수신: data=${message.data}")

        val title = message.notification?.title
            ?: message.data["title"]
            ?: "HeyGent"
        val body = message.notification?.body
            ?: message.data["body"]
            ?: "새 AI 응답이 도착했습니다."
        val sessionId = message.data["sessionId"]

        // 앱 내 채팅 화면 갱신 트리거 (포그라운드/백그라운드 공통)
        FcmEventBus.emitRefresh(sessionId)

        showNotification(title, body, sessionId)
    }

    private fun showNotification(title: String, body: String, sessionId: String?) {
        val channelId = "ai_chat_v2"
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager

        // 채널 생성 (Android 8+)
        val channel = NotificationChannel(
            channelId, "AI 채팅 알림", NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "AI 응답 완료 알림"
            setShowBadge(false)
        }
        nm.createNotificationChannel(channel)

        // 탭 시 해당 세션으로 이동
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            sessionId?.let { putExtra("sessionId", it) }
        }
        val pendingIntent = PendingIntent.getActivity(
            this, sessionId.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .build()

        nm.notify(System.currentTimeMillis().toInt(), notification)
    }
}
