package com.example.mob.feature.chat

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import java.util.Locale
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.example.mob.BuildConfig
import com.example.mob.ui.theme.*
import com.example.mob.voice.WakeWordForegroundService
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import androidx.compose.ui.geometry.Size as GeomSize

data class ChatMessage(
    val isBot: Boolean,
    val text: String,
    val timestamp: String,
    val isTyping: Boolean = false,
)

@Composable
fun BotMessageBubble(
    message: ChatMessage,
    agentName: String = "HeyGent",
) {
    Column(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
    ) {
        Text(
            text = agentName,
            fontSize = 12.sp,
            color = TextSecondary,
            modifier = Modifier.padding(start = 4.dp, bottom = 4.dp),
        )
        val botShape = RoundedCornerShape(topStart = 4.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 16.dp)
        if (message.isTyping) {
            Box(
                modifier =
                    Modifier
                        .clip(botShape)
                        .background(BotBubbleColor)
                        .border(1.dp, BubbleBorder, botShape)
                        .padding(horizontal = 16.dp, vertical = 14.dp),
            ) {
                TypingIndicator()
            }
        } else {
            Row(verticalAlignment = Alignment.Bottom) {
                Box(
                    modifier =
                        Modifier
                            .widthIn(max = 260.dp)
                            .clip(botShape)
                            .background(BotBubbleColor)
                            .border(1.dp, BubbleBorder, botShape)
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                ) {
                    Text(message.text, fontSize = 14.sp, color = TextPrimary, lineHeight = 20.sp)
                }
                Spacer(modifier = Modifier.width(6.dp))
                Text(
                    text = message.timestamp,
                    fontSize = 10.sp,
                    color = TextSecondary,
                    lineHeight = 14.sp,
                )
            }
        }
    }
}

@Composable
fun UserMessageBubble(message: ChatMessage) {
    Column(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.End,
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                text = message.timestamp,
                fontSize = 10.sp,
                color = TextSecondary,
                lineHeight = 14.sp,
            )
            Spacer(modifier = Modifier.width(6.dp))
            Box(
                modifier =
                    Modifier
                        .widthIn(max = 260.dp)
                        .clip(RoundedCornerShape(topStart = 16.dp, topEnd = 4.dp, bottomStart = 16.dp, bottomEnd = 16.dp))
                        .background(UserBubbleColor)
                        .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                Text(
                    text = message.text,
                    fontSize = 14.sp,
                    color = TextPrimary,
                    lineHeight = 20.sp,
                    fontWeight = FontWeight.Medium,
                )
            }
        }
    }
}

@Composable
fun TaskStatusBanner(taskName: String) {
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .background(SurfaceWarm)
                .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier =
                Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(ActiveGreen),
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text("Current Task", fontSize = 11.sp, color = TextSecondary)
            Text(taskName, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = TextPrimary)
        }
        Text("Processing...", fontSize = 12.sp, color = TextSecondary)
    }
}

@Composable
fun TypingIndicator() {
    val infiniteTransition = rememberInfiniteTransition(label = "typing")
    val alphas =
        (0..2).map { i ->
            infiniteTransition.animateFloat(
                initialValue = 0.3f,
                targetValue = 1.0f,
                animationSpec =
                    infiniteRepeatable(
                        animation = tween(400, delayMillis = i * 140, easing = FastOutSlowInEasing),
                        repeatMode = RepeatMode.Reverse,
                    ),
                label = "dot$i",
            )
        }
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        alphas.forEach { alpha ->
            Box(
                modifier =
                    Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(TextSecondary.copy(alpha = alpha.value)),
            )
        }
        Spacer(modifier = Modifier.width(4.dp))
        Text("처리 중...", fontSize = 13.sp, color = TextSecondary)
    }
}

@Composable
fun ChatInputBar(
    inputText: String,
    onInputChange: (String) -> Unit,
    isProcessing: Boolean,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onPlusClick: () -> Unit = {},
    onVoiceMode: () -> Unit = {},
    placeholder: String = "HeyGent 어시스턴트에게 질문하세요...",
) {
    var isRecording by remember { mutableStateOf(false) }
    var isTranscribing by remember { mutableStateOf(false) }
    var amplitude by remember { mutableStateOf(0f) }
    val context = LocalContext.current

    val recorderRef = remember { mutableStateOf<MediaRecorder?>(null) }
    val audioFileRef = remember { mutableStateOf<File?>(null) }

    val permissionLauncher =
        rememberLauncherForActivityResult(
            ActivityResultContracts.RequestPermission(),
        ) { granted -> if (granted) isRecording = true }

    // 화면 이탈 시 정리
    DisposableEffect(Unit) {
        onDispose {
            recorderRef.value?.let {
                try {
                    it.stop()
                    it.release()
                } catch (_: Exception) {
                }
            }
            recorderRef.value = null
        }
    }

    // 녹음 시작/종료 + Whisper 전사
    LaunchedEffect(isRecording) {
        if (isRecording) {
            // --- 녹음 시작 ---
            Log.d("WhisperSTT", "녹음 시작")
            val file = File(context.cacheDir, "whisper_input.m4a")
            if (file.exists()) file.delete()
            audioFileRef.value = file

            @Suppress("DEPRECATION")
            val recorder =
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    MediaRecorder(context)
                } else {
                    MediaRecorder()
                }
            try {
                recorder.apply {
                    setAudioSource(MediaRecorder.AudioSource.MIC)
                    setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                    setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                    setAudioSamplingRate(16000)
                    setAudioChannels(1)
                    setOutputFile(file.absolutePath)
                    prepare()
                    start()
                }
                recorderRef.value = recorder
                Log.d("WhisperSTT", "MediaRecorder 시작 성공")
                // 진폭 폴링 (파형 애니메이션용)
                while (isActive) {
                    delay(80)
                    val amp = recorderRef.value?.maxAmplitude ?: 0
                    amplitude = (amp.toFloat() / 8000f).coerceIn(0f, 1f)
                }
            } catch (e: CancellationException) {
                // 유저가 중지 버튼 탭 → Compose가 코루틴 취소
                // recorderRef는 그대로 유지 — isRecording=false LaunchedEffect에서 cleanup
                Log.d("WhisperSTT", "녹음 코루틴 취소됨 (정상)")
                throw e // 반드시 re-throw
            } catch (e: Exception) {
                Log.e("WhisperSTT", "MediaRecorder 시작 실패: ${e.javaClass.simpleName} ${e.message}", e)
                try {
                    recorder.release()
                } catch (_: Exception) {
                }
                recorderRef.value = null
                isRecording = false
            }
        } else {
            // --- 녹음 종료 → Whisper API 전사 ---
            amplitude = 0f
            val recorder = recorderRef.value
            val file = audioFileRef.value
            recorderRef.value = null

            Log.d("WhisperSTT", "녹음 종료 — recorder=$recorder, file=$file, fileSize=${file?.length()}")

            if (recorder != null) {
                try {
                    recorder.stop()
                    recorder.release()
                } catch (e: Exception) {
                    Log.w("WhisperSTT", "recorder.stop 예외 (무시): ${e.message}")
                }

                val fileSize = file?.length() ?: 0L
                Log.d("WhisperSTT", "파일 크기: $fileSize bytes")

                if (file != null && file.exists() && fileSize > 0L) {
                    isTranscribing = true
                    Log.d("WhisperSTT", "Whisper API 호출 시작, apiKey=${BuildConfig.OPENAI_API_KEY.take(8)}...")
                    withContext(Dispatchers.IO) {
                        val result = callWhisperApi(file)
                        Log.d("WhisperSTT", "Whisper 결과: '$result'")
                        withContext(Dispatchers.Main) {
                            if (result.isNotBlank()) onInputChange(result)
                            isTranscribing = false
                        }
                    }
                } else {
                    Log.w("WhisperSTT", "파일 없음 또는 크기 0 — 전사 스킵")
                }
            } else {
                Log.w("WhisperSTT", "recorder null — MediaRecorder가 시작되지 않았음")
            }
        }
    }

    Surface(shadowElevation = 8.dp, color = SurfaceWhite) {
        Row(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!isRecording && !isTranscribing) {
                IconButton(onClick = onPlusClick, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Default.Add, contentDescription = null, tint = TextSecondary)
                }
                Spacer(modifier = Modifier.width(6.dp))
            }

            Box(
                modifier =
                    Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(24.dp))
                        .background(AppBackground)
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                when {
                    isRecording && inputText.isEmpty() -> {
                        RecordingWaveform(amplitude)
                    }

                    isTranscribing -> {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                                color = NavyPrimary,
                            )
                            Spacer(Modifier.width(8.dp))
                            Text("변환 중...", color = TextSecondary, fontSize = 14.sp)
                        }
                    }

                    isProcessing -> {
                        Text("응답을 기다리는 중...", color = TextSecondary, fontSize = 14.sp)
                    }

                    else -> {
                        BasicTextField(
                            value = inputText,
                            onValueChange = onInputChange,
                            modifier = Modifier.fillMaxWidth(),
                            maxLines = 4,
                            textStyle = TextStyle(fontSize = 14.sp, color = TextPrimary),
                            cursorBrush = SolidColor(NavyPrimary),
                            decorationBox = { innerTextField ->
                                Box {
                                    if (inputText.isEmpty()) {
                                        Text(placeholder, color = TextHint, fontSize = 14.sp)
                                    }
                                    innerTextField()
                                }
                            },
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.width(6.dp))

            // 마이크 버튼 (전사 중에는 비활성)
            if (!isProcessing) {
                IconButton(
                    onClick = {
                        if (isTranscribing) return@IconButton
                        if (isRecording) {
                            isRecording = false
                        } else {
                            val granted =
                                ContextCompat.checkSelfPermission(
                                    context,
                                    Manifest.permission.RECORD_AUDIO,
                                ) == PackageManager.PERMISSION_GRANTED
                            if (granted) {
                                onInputChange("")
                                isRecording = true
                            } else {
                                permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                            }
                        }
                    },
                    modifier = Modifier.size(36.dp),
                ) {
                    Icon(
                        Icons.Default.Mic,
                        contentDescription = null,
                        tint =
                            when {
                                isTranscribing -> TextHint
                                isRecording -> HealthRed
                                else -> TextSecondary
                            },
                    )
                }
                Spacer(modifier = Modifier.width(4.dp))
            }

            // 우측 액션 버튼
            when {
                isProcessing -> {
                    Box(
                        modifier =
                            Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(HealthRed)
                                .clickable { onStop() },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Default.Stop, contentDescription = "정지", tint = Color.White, modifier = Modifier.size(20.dp))
                    }
                }

                isRecording -> {
                    Box(
                        modifier =
                            Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(NavyPrimary)
                                .clickable { isRecording = false },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "전송", tint = Color.White, modifier = Modifier.size(18.dp))
                    }
                }

                isTranscribing -> {
                    Box(
                        modifier =
                            Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(NavyPrimary.copy(alpha = 0.4f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = Color.White,
                        )
                    }
                }

                inputText.isNotBlank() -> {
                    Box(
                        modifier =
                            Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(NavyPrimary)
                                .clickable { onSend() },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "전송", tint = Color.White, modifier = Modifier.size(18.dp))
                    }
                }

                else -> {
                    Box(
                        modifier =
                            Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(NavyPrimary)
                                .clickable { onVoiceMode() },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Default.GraphicEq, contentDescription = "음성 대화", tint = Color.White, modifier = Modifier.size(22.dp))
                    }
                }
            }
        }
    }
}

/** OpenAI Whisper API 호출 — IO 스레드에서 호출할 것 */
private fun callWhisperApi(file: File): String {
    return try {
        val client =
            OkHttpClient
                .Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .build()

        val body =
            MultipartBody
                .Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "file",
                    file.name,
                    file.asRequestBody("audio/m4a".toMediaType()),
                ).addFormDataPart("model", "whisper-1")
                .addFormDataPart("language", "ko")
                .build()

        val request =
            Request
                .Builder()
                .url("https://api.openai.com/v1/audio/transcriptions")
                .header("Authorization", "Bearer ${BuildConfig.OPENAI_API_KEY}")
                .post(body)
                .build()

        client.newCall(request).execute().use { response ->
            val raw = response.body?.string() ?: ""
            Log.d("WhisperSTT", "HTTP ${response.code}: $raw")
            if (!response.isSuccessful) return ""
            JSONObject(raw).optString("text", "")
        }
    } catch (e: Exception) {
        Log.e("WhisperSTT", "callWhisperApi 예외: ${e.message}", e)
        ""
    }
}

@Composable
private fun RecordingWaveform(amplitude: Float) {
    val multipliers = remember { listOf(0.4f, 0.62f, 0.82f, 1.0f, 0.82f, 0.62f, 0.4f) }

    val animatedHeights =
        multipliers.map { mult ->
            animateFloatAsState(
                targetValue = (amplitude * mult).coerceAtLeast(0.08f),
                animationSpec = spring(dampingRatio = 0.5f, stiffness = 280f),
                label = "",
            ).value
        }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("녹음 중", fontSize = 13.sp, color = HealthRed)
        Spacer(Modifier.width(10.dp))
        Canvas(
            modifier =
                Modifier
                    .width(64.dp)
                    .height(24.dp),
        ) {
            val barW = 4.dp.toPx()
            val gap = 4.dp.toPx()
            val total = 7 * barW + 6 * gap
            val startX = (size.width - total) / 2f
            animatedHeights.forEachIndexed { i, h ->
                val barH = size.height * h
                val x = startX + i * (barW + gap)
                val y = (size.height - barH) / 2f
                drawRoundRect(
                    color = Color(0xFFEF5350),
                    topLeft = Offset(x, y),
                    size = GeomSize(barW, barH),
                    cornerRadius = CornerRadius(2.dp.toPx()),
                )
            }
        }
    }
}

/**
 * 풀스크린 음성 입력 오버레이.
 * - 화면 전체를 어둡게 덮음 (푸터 위 포함)
 * - 시스템 SpeechRecognizer로 한국어 실시간 인식
 *   · onPartialResults: 진행 중인 부분 텍스트
 *   · onResults: 한 발화 완료, finalText에 누적 후 다음 세션 재시작
 *   · onError: ERROR_NO_MATCH / TIMEOUT 등은 정상 — 재시작
 * - onRmsChanged 값으로 큰 웨이브바를 구동 (입력 음량에 따라 움직임)
 * - 전송 버튼: 현재까지 누적된 텍스트(final + partial)를 onSend로 즉시 전달
 * - 중단 버튼: 그냥 닫음
 * - 진입 시 WakeWordForegroundService를 일시중단(마이크 자원 회피), 닫힐 때 재개
 *
 * @param bottomInset 시스템 네비 인셋 (버튼이 푸터/시스템바에 가려지지 않도록)
 */
@Composable
fun VoiceCaptureOverlay(
    bottomInset: Dp,
    onSend: (String) -> Unit,
    onCancel: () -> Unit,
) {
    val context = LocalContext.current

    var amplitude by remember { mutableStateOf(0f) }
    var isPreparing by remember { mutableStateOf(true) }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var finalText by remember { mutableStateOf("") }
    var partialText by remember { mutableStateOf("") }

    val recognizerRef = remember { mutableStateOf<SpeechRecognizer?>(null) }
    // 세션이 활성 상태인지 (false면 onResults/onError 시 재시작 안 함)
    val sessionActive = remember { mutableStateOf(true) }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }

    // ─── 한 사이클의 startListening ───────────────────────────────────────
    val startRecognizing: () -> Unit = startFn@{
        val recognizer = recognizerRef.value ?: return@startFn
        val intent =
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.KOREAN.toLanguageTag())
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
            }
        try {
            recognizer.startListening(intent)
            Log.d("VoiceOverlay", "SpeechRecognizer startListening")
        } catch (e: Exception) {
            Log.e("VoiceOverlay", "startListening 실패: ${e.message}", e)
            statusMessage = "음성 인식을 시작할 수 없습니다"
        }
    }

    // ─── 초기화 ──────────────────────────────────────────────────────────
    LaunchedEffect(Unit) {
        Log.d("VoiceOverlay", "오버레이 진입 — 웨이크 워드 일시중단")
        WakeWordForegroundService.pauseListening(context)
        // 웨이크 워드의 SpeechRecognizer가 destroy되어 마이크가 풀릴 시간 확보
        delay(350)

        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            statusMessage = "이 기기는 음성 인식을 지원하지 않습니다"
            isPreparing = false
            return@LaunchedEffect
        }

        val hasMicPerm =
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        if (!hasMicPerm) {
            statusMessage = "마이크 권한이 없습니다"
            isPreparing = false
            return@LaunchedEffect
        }

        val recognizer = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer.setRecognitionListener(
            object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    Log.d("VoiceOverlay", "onReadyForSpeech")
                    isPreparing = false
                    statusMessage = null
                }

                override fun onBeginningOfSpeech() {
                    Log.d("VoiceOverlay", "onBeginningOfSpeech")
                }

                override fun onRmsChanged(rmsdB: Float) {
                    // rmsDb는 대략 -2 ~ 10 dB 범위. 0..1로 정규화.
                    amplitude = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
                }

                override fun onBufferReceived(buffer: ByteArray?) = Unit

                override fun onEndOfSpeech() {
                    Log.d("VoiceOverlay", "onEndOfSpeech")
                    amplitude = 0f
                }

                override fun onError(error: Int) {
                    Log.w("VoiceOverlay", "Recognizer error: ${errorName(error)}")
                    amplitude = 0f
                    if (!sessionActive.value) return
                    // NO_MATCH / TIMEOUT / CLIENT 등은 정상적인 끊김 — 재시작
                    when (error) {
                        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> {
                            mainHandler.postDelayed({ startRecognizing() }, 400)
                        }
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> {
                            statusMessage = "마이크 권한이 없습니다"
                        }
                        SpeechRecognizer.ERROR_NETWORK,
                        SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
                        -> {
                            statusMessage = "네트워크 오류 — 다시 시도해 주세요"
                            mainHandler.postDelayed({
                                statusMessage = null
                                startRecognizing()
                            }, 1500)
                        }
                        else -> {
                            mainHandler.postDelayed({ startRecognizing() }, 250)
                        }
                    }
                }

                override fun onResults(results: Bundle?) {
                    val matches =
                        results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                    val best = matches.firstOrNull().orEmpty().trim()
                    Log.d("VoiceOverlay", "onResults: '$best'")
                    if (best.isNotEmpty()) {
                        finalText =
                            if (finalText.isEmpty()) best else "$finalText $best"
                    }
                    partialText = ""
                    amplitude = 0f
                    if (sessionActive.value) {
                        mainHandler.postDelayed({ startRecognizing() }, 150)
                    }
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val matches =
                        partialResults
                            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            .orEmpty()
                    partialText = matches.firstOrNull().orEmpty()
                }

                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            },
        )
        recognizerRef.value = recognizer
        startRecognizing()
    }

    // ─── 정리 ────────────────────────────────────────────────────────────
    DisposableEffect(Unit) {
        onDispose {
            sessionActive.value = false
            mainHandler.removeCallbacksAndMessages(null)
            try { recognizerRef.value?.cancel() } catch (_: Exception) {}
            try { recognizerRef.value?.destroy() } catch (_: Exception) {}
            recognizerRef.value = null
            WakeWordForegroundService.resumeListening(context)
            Log.d("VoiceOverlay", "오버레이 종료 — 웨이크 워드 재개")
        }
    }

    // ─── 버튼 핸들러 ─────────────────────────────────────────────────────
    val handleSend: () -> Unit = handle@{
        val combined = (finalText + " " + partialText).trim()
        Log.d("VoiceOverlay", "전송 탭 — final='$finalText' partial='$partialText' combined='$combined'")
        if (combined.isBlank()) {
            statusMessage = "음성을 인식하지 못했습니다. 다시 말씀해 주세요."
            return@handle
        }
        sessionActive.value = false
        mainHandler.removeCallbacksAndMessages(null)
        try { recognizerRef.value?.cancel() } catch (_: Exception) {}
        onSend(combined)
    }

    val handleCancel: () -> Unit = { onCancel() }

    // ─── UI ──────────────────────────────────────────────────────────────
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .background(Color.Black),
    ) {
        if (isPreparing) {
            Column(
                modifier = Modifier.align(Alignment.Center),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                CircularProgressIndicator(
                    color = Color.White,
                    strokeWidth = 3.dp,
                    modifier = Modifier.size(48.dp),
                )
                Spacer(Modifier.height(20.dp))
                Text("준비 중...", color = Color.White.copy(alpha = 0.85f), fontSize = 16.sp)
            }
        } else {
            BigVolumeWaveBar(
                amplitude = amplitude,
                modifier =
                    Modifier
                        .align(Alignment.Center)
                        .fillMaxWidth()
                        .padding(horizontal = 32.dp)
                        .height(180.dp),
            )

            // 인식 텍스트 미리보기 (final + partial)
            val transcript = (finalText + " " + partialText).trim()
            Text(
                if (statusMessage != null) statusMessage!!
                else if (transcript.isNotBlank()) transcript
                else "말씀해 주세요...",
                color =
                    when {
                        statusMessage != null -> HealthRed.copy(alpha = 0.95f)
                        transcript.isNotBlank() -> Color.White
                        else -> Color.White.copy(alpha = 0.6f)
                    },
                fontSize = if (statusMessage != null) 15.sp else 17.sp,
                fontWeight = FontWeight.Medium,
                modifier =
                    Modifier
                        .align(Alignment.Center)
                        .offset(y = 150.dp)
                        .padding(horizontal = 24.dp),
            )
        }

        Row(
            modifier =
                Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = bottomInset + 56.dp),
            horizontalArrangement = Arrangement.spacedBy(48.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                    modifier =
                        Modifier
                            .size(72.dp)
                            .clip(CircleShape)
                            .background(HealthRed)
                            .clickable { handleCancel() },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Default.Close,
                        contentDescription = "중단",
                        tint = Color.White,
                        modifier = Modifier.size(32.dp),
                    )
                }
                Spacer(Modifier.height(8.dp))
                Text("중단", color = Color.White, fontSize = 13.sp)
            }

            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                    modifier =
                        Modifier
                            .size(72.dp)
                            .clip(CircleShape)
                            .background(NavyPrimary)
                            .clickable { handleSend() },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.AutoMirrored.Filled.Send,
                        contentDescription = "전송",
                        tint = Color.White,
                        modifier = Modifier.size(30.dp),
                    )
                }
                Spacer(Modifier.height(8.dp))
                Text("전송", color = Color.White, fontSize = 13.sp)
            }
        }
    }
}

private fun errorName(error: Int): String =
    when (error) {
        SpeechRecognizer.ERROR_AUDIO -> "ERROR_AUDIO"
        SpeechRecognizer.ERROR_CLIENT -> "ERROR_CLIENT"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "ERROR_INSUFFICIENT_PERMISSIONS"
        SpeechRecognizer.ERROR_NETWORK -> "ERROR_NETWORK"
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "ERROR_NETWORK_TIMEOUT"
        SpeechRecognizer.ERROR_NO_MATCH -> "ERROR_NO_MATCH"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "ERROR_RECOGNIZER_BUSY"
        SpeechRecognizer.ERROR_SERVER -> "ERROR_SERVER"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "ERROR_SPEECH_TIMEOUT"
        else -> "UNKNOWN($error)"
    }

@Composable
private fun BigVolumeWaveBar(
    amplitude: Float,
    modifier: Modifier = Modifier,
) {
    val barCount = 19
    val multipliers =
        remember {
            val center = (barCount - 1) / 2f
            (0 until barCount).map { i ->
                val dist = kotlin.math.abs(i - center) / center
                (1f - dist * 0.55f).coerceIn(0.35f, 1f)
            }
        }

    val animatedAmps =
        multipliers.mapIndexed { i, mult ->
            val jitter = if (amplitude > 0.05f) ((i * 37) % 17) / 60f else 0f
            val target = (amplitude * mult + jitter).coerceIn(0.04f, 1f)
            animateFloatAsState(
                targetValue = target,
                animationSpec = spring(dampingRatio = 0.5f, stiffness = 320f),
                label = "amp$i",
            ).value
        }

    Canvas(modifier = modifier) {
        val barW = 10.dp.toPx()
        val gap = 8.dp.toPx()
        val total = barCount * barW + (barCount - 1) * gap
        val startX = (size.width - total) / 2f
        val centerY = size.height / 2f
        val maxH = size.height

        animatedAmps.forEachIndexed { i, amp ->
            val h = (maxH * amp).coerceAtLeast(barW)
            val x = startX + i * (barW + gap)
            val y = centerY - h / 2f
            drawRoundRect(
                color = Color.White,
                topLeft = Offset(x, y),
                size = GeomSize(barW, h),
                cornerRadius = CornerRadius(barW / 2f),
            )
        }
    }
}
