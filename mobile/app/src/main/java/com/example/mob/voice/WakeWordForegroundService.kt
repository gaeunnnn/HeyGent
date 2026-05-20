package com.example.mob.voice

import android.Manifest
import android.app.ActivityOptions
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import com.example.mob.MainActivity
import com.example.mob.R
import java.util.Locale

class WakeWordForegroundService : Service(), RecognitionListener {
    private val mainHandler = Handler(Looper.getMainLooper())
    private var speechRecognizer: SpeechRecognizer? = null
    private var isListening = false
    private var isPaused = false
    private var lastLaunchAtMillis = 0L
    private var lastRmsLogAtMillis = 0L
    private var lastLevelBucket = -1
    private var wakeOverlayView: View? = null

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "Wake word service created.")
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())

        if (hasAudioPermission()) {
            createRecognizer()
            startListening()
        } else {
            Log.w(TAG, "Missing RECORD_AUDIO permission. Stopping service.")
            stopSelf()
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        Log.d(TAG, "Wake word service start requested. action=$action paused=$isPaused")

        when (action) {
            ACTION_PAUSE_LISTENING -> {
                isPaused = true
                mainHandler.removeCallbacksAndMessages(null)
                // 마이크 자원을 즉시 해제하기 위해 인스턴스 자체를 파괴한다.
                // cancel/stop만으로는 오디오 프레임워크 레벨에서 즉시 해제되지 않는 경우가 있다.
                try { speechRecognizer?.cancel() } catch (_: Exception) {}
                try { speechRecognizer?.stopListening() } catch (_: Exception) {}
                try { speechRecognizer?.destroy() } catch (_: Exception) {}
                speechRecognizer = null
                isListening = false
                Log.d(TAG, "Wake word listener paused (recognizer destroyed).")
                return START_STICKY
            }
            ACTION_RESUME_LISTENING -> {
                isPaused = false
                if (!hasAudioPermission()) {
                    stopSelf()
                    return START_NOT_STICKY
                }
                if (speechRecognizer == null) createRecognizer()
                startListening()
                Log.d(TAG, "Wake word listener resumed.")
                return START_STICKY
            }
        }

        if (!hasAudioPermission()) {
            Log.w(TAG, "Missing RECORD_AUDIO permission on start command.")
            stopSelf()
            return START_NOT_STICKY
        }

        if (speechRecognizer == null) {
            createRecognizer()
        }
        if (!isPaused) startListening()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        Log.d(TAG, "Wake word service destroyed.")
        mainHandler.removeCallbacksAndMessages(null)
        speechRecognizer?.destroy()
        speechRecognizer = null
        super.onDestroy()
    }

    override fun onReadyForSpeech(params: Bundle?) {
        Log.d(TAG, "Ready for wake word speech.")
    }

    override fun onBeginningOfSpeech() {
        Log.d(TAG, "Speech started.")
    }

    override fun onRmsChanged(rmsdB: Float) {
        val level = rmsDbToLevel(rmsdB)
        val bucket = level / 10
        val now = System.currentTimeMillis()

        if (bucket != lastLevelBucket || now - lastRmsLogAtMillis >= RMS_LOG_INTERVAL_MS) {
            lastLevelBucket = bucket
            lastRmsLogAtMillis = now
            //Log.d(TAG, "Mic level: $level/100 (rms=${"%.1f".format(Locale.US, rmsdB)}dB)")
        }
    }

    override fun onBufferReceived(buffer: ByteArray?) = Unit

    override fun onEndOfSpeech() {
        Log.d(TAG, "Speech ended.")
        isListening = false
    }

    override fun onError(error: Int) {
        Log.w(TAG, "Speech recognizer error: ${error.toRecognizerErrorName()}")
        isListening = false
        scheduleRestart(RESTART_DELAY_MS)
    }

    override fun onResults(results: Bundle?) {
        isListening = false
        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
        Log.d(TAG, "Wake word final results: $matches")
        handleMatches(matches)
        scheduleRestart(RESTART_DELAY_MS)
    }

    override fun onPartialResults(partialResults: Bundle?) {
        val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
        Log.d(TAG, "Wake word partial results: $matches")
        handleMatches(matches)
    }

    override fun onEvent(eventType: Int, params: Bundle?) = Unit

    private fun createRecognizer() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            Log.w(TAG, "Speech recognition is not available on this device.")
            stopSelf()
            return
        }

        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(this@WakeWordForegroundService)
        }
    }

    private fun startListening() {
        if (isPaused || isListening || speechRecognizer == null) return

        Log.d(TAG, "Start listening for wake word.")
        isListening = true
        speechRecognizer?.startListening(
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.KOREAN.toLanguageTag())
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
                putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, packageName)
            }
        )
    }

    private fun stopCurrentListening() {
        try { speechRecognizer?.cancel() } catch (_: Exception) {}
        try { speechRecognizer?.stopListening() } catch (_: Exception) {}
        isListening = false
    }

    private fun scheduleRestart(delayMillis: Long) {
        if (isPaused) return
        mainHandler.postDelayed({ startListening() }, delayMillis)
    }

    private fun handleMatches(matches: List<String>) {
        val detected = matches
            .map { it.normalizeWakeWord() }
            .any { normalized -> WAKE_WORDS.any { wakeWord -> normalized.contains(wakeWord) } }

        if (detected) {
            Log.d(TAG, "Wake word detected from matches: $matches")
            bringAppToForeground()
        }
    }

    private fun bringAppToForeground() {
        val now = System.currentTimeMillis()
        if (now - lastLaunchAtMillis < LAUNCH_COOLDOWN_MS) return

        lastLaunchAtMillis = now
        showWakeDetectedNotification()

        if (Settings.canDrawOverlays(this)) {
            showWakeOverlayThenLaunch()
        } else {
            Log.w(TAG, "Overlay permission is missing. System may block background activity launch.")
            launchMainActivityFromWakeWord()
        }
    }

    private fun showWakeOverlayThenLaunch() {
        showWakeOverlay()
        mainHandler.postDelayed({ launchMainActivityFromWakeWord() }, OVERLAY_LAUNCH_DELAY_MS)
        mainHandler.postDelayed({ hideWakeOverlay() }, OVERLAY_HIDE_DELAY_MS)
    }

    private fun showWakeOverlay() {
        hideWakeOverlay()

        val overlay = TextView(this).apply {
            text = "\uC820\uD2B8\uAC00 \uD638\uCD9C\uC744 \uAC10\uC9C0\uD588\uC2B5\uB2C8\uB2E4"
            setTextColor(Color.WHITE)
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(28, 18, 28, 18)
            background = GradientDrawable().apply {
                setColor(Color.argb(235, 13, 20, 38))
                cornerRadius = 32f
            }
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = 96
        }

        try {
            getSystemService(WindowManager::class.java).addView(overlay, params)
            wakeOverlayView = overlay
            Log.d(TAG, "Wake overlay shown before activity launch.")
        } catch (e: RuntimeException) {
            Log.e(TAG, "Failed to show wake overlay.", e)
        }
    }

    private fun hideWakeOverlay() {
        val overlay = wakeOverlayView ?: return
        wakeOverlayView = null
        try {
            getSystemService(WindowManager::class.java).removeView(overlay)
        } catch (e: RuntimeException) {
            Log.w(TAG, "Failed to remove wake overlay.", e)
        }
    }

    private fun launchMainActivityFromWakeWord() {
        val pendingIntent = mainActivityPendingIntent(WAKE_DETECTED_REQUEST_CODE)

        try {
            Log.d(TAG, "Launching MainActivity via PendingIntent from wake word.")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                pendingIntent.send(
                    this,
                    0,
                    null,
                    null,
                    null,
                    null,
                    backgroundActivityStartOptions().toBundle()
                )
            } else {
                pendingIntent.send()
            }
        } catch (e: PendingIntent.CanceledException) {
            Log.e(TAG, "Failed to launch MainActivity pending intent.", e)
        } catch (e: RuntimeException) {
            Log.e(TAG, "Background MainActivity launch was blocked by the system.", e)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_wake_word)
            .setContentTitle("\uC820\uD2B8 \uD638\uCD9C \uB300\uAE30 \uC911")
            .setContentText("\"\uC820\uD2B8\uC57C\"\uB77C\uACE0 \uBD80\uB974\uBA74 \uC571\uC744 \uC5FD\uB2C8\uB2E4.")
            .setContentIntent(mainActivityPendingIntent(NOTIFICATION_REQUEST_CODE))
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateListeningNotification(text: String) {
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_wake_word)
            .setContentTitle("\uC820\uD2B8 \uD638\uCD9C \uB300\uAE30 \uC911")
            .setContentText(text)
            .setContentIntent(mainActivityPendingIntent(WAKE_DETECTED_NOTIFICATION_REQUEST_CODE))
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification)
    }

    private fun showWakeDetectedNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !hasPostNotificationPermission()) {
            Log.w(TAG, "Cannot post wake detected notification without POST_NOTIFICATIONS permission.")
            return
        }

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_wake_word)
            .setContentTitle("\uC820\uD2B8\uAC00 \uD638\uCD9C\uC744 \uAC10\uC9C0\uD588\uC2B5\uB2C8\uB2E4")
            .setContentText("\uC571\uC774 \uC790\uB3D9\uC73C\uB85C \uC548 \uC5F4\uB9AC\uBA74 \uC54C\uB9BC\uC744 \uD0ED\uD558\uC138\uC694.")
            .setContentIntent(mainActivityPendingIntent(WAKE_DETECTED_NOTIFICATION_REQUEST_CODE))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        getSystemService(NotificationManager::class.java)
            .notify(WAKE_DETECTED_NOTIFICATION_ID, notification)
    }

    private fun mainActivityPendingIntent(requestCode: Int): PendingIntent {
        val intent = Intent(this, MainActivity::class.java).apply {
            action = ACTION_WAKE_WORD_DETECTED
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }

        val options = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            backgroundActivityStartCreatorOptions().toBundle()
        } else {
            null
        }

        return PendingIntent.getActivity(
            this,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            options
        )
    }

    @Suppress("DEPRECATION")
    private fun backgroundActivityStartOptions(): ActivityOptions {
        return ActivityOptions.makeBasic().apply {
            setPendingIntentBackgroundActivityStartMode(
                ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED
            )
        }
    }

    @Suppress("DEPRECATION")
    private fun backgroundActivityStartCreatorOptions(): ActivityOptions {
        return ActivityOptions.makeBasic().apply {
            setPendingIntentCreatorBackgroundActivityStartMode(
                ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED
            )
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val channel = NotificationChannel(
            CHANNEL_ID,
            "Wake word listener",
            NotificationManager.IMPORTANCE_LOW
        ).apply { setShowBadge(false) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun hasAudioPermission(): Boolean {
        return ActivityCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun hasPostNotificationPermission(): Boolean {
        return ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun String.normalizeWakeWord(): String {
        return lowercase(Locale.KOREAN).replace(" ", "")
    }

    private fun Int.toRecognizerErrorName(): String {
        return when (this) {
            SpeechRecognizer.ERROR_AUDIO -> "ERROR_AUDIO"
            SpeechRecognizer.ERROR_CLIENT -> "ERROR_CLIENT"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "ERROR_INSUFFICIENT_PERMISSIONS"
            SpeechRecognizer.ERROR_NETWORK -> "ERROR_NETWORK"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "ERROR_NETWORK_TIMEOUT"
            SpeechRecognizer.ERROR_NO_MATCH -> "ERROR_NO_MATCH"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "ERROR_RECOGNIZER_BUSY"
            SpeechRecognizer.ERROR_SERVER -> "ERROR_SERVER"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "ERROR_SPEECH_TIMEOUT"
            else -> "UNKNOWN($this)"
        }
    }

    private fun rmsDbToLevel(rmsDb: Float): Int {
        return ((rmsDb + 2f) * 8f)
            .toInt()
            .coerceIn(0, 100)
    }

    private fun Int.toLevelBar(): String {
        val filled = (this / 10).coerceIn(0, 10)
        return buildString {
            repeat(filled) { append('#') }
            repeat(10 - filled) { append('-') }
        }
    }

    companion object {
        const val ACTION_WAKE_WORD_DETECTED = "com.example.mob.action.WAKE_WORD_DETECTED"
        const val ACTION_PAUSE_LISTENING = "com.example.mob.action.WAKE_WORD_PAUSE"
        const val ACTION_RESUME_LISTENING = "com.example.mob.action.WAKE_WORD_RESUME"
        private const val CHANNEL_ID = "wake_word_listener_v2"
        private const val NOTIFICATION_ID = 1001
        private const val WAKE_DETECTED_NOTIFICATION_ID = 1002
        private const val NOTIFICATION_REQUEST_CODE = 2001
        private const val WAKE_DETECTED_NOTIFICATION_REQUEST_CODE = 2002
        private const val WAKE_DETECTED_REQUEST_CODE = 2003
        private const val RESTART_DELAY_MS = 700L
        private const val LAUNCH_COOLDOWN_MS = 3_000L
        private const val OVERLAY_LAUNCH_DELAY_MS = 350L
        private const val OVERLAY_HIDE_DELAY_MS = 2_500L
        private const val RMS_LOG_INTERVAL_MS = 1_000L
        private const val TAG = "WakeWordService"
        private val WAKE_WORDS = listOf("\uC820\uD2B8\uC57C", "\uC820\uD2B8")

        fun start(context: Context) {
            val intent = Intent(context, WakeWordForegroundService::class.java)
            launchService(context, intent)
        }

        fun pauseListening(context: Context) {
            val intent = Intent(context, WakeWordForegroundService::class.java).apply {
                action = ACTION_PAUSE_LISTENING
            }
            launchService(context, intent)
        }

        fun resumeListening(context: Context) {
            val intent = Intent(context, WakeWordForegroundService::class.java).apply {
                action = ACTION_RESUME_LISTENING
            }
            launchService(context, intent)
        }

        private fun launchService(context: Context, intent: Intent) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}
