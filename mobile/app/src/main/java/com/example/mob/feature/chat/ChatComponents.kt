package com.example.mob.feature.chat

import android.Manifest
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
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
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.example.mob.BuildConfig
import com.example.mob.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
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

@Composable
fun VoiceModeOverlay(onStop: () -> Unit) {
    val transition = rememberInfiniteTransition(label = "voice")
    var isSpeaking by remember { mutableStateOf(false) }
    var isMicOn by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(3000)
            isSpeaking = !isSpeaking
        }
    }

    val pulse1 =
        transition.animateFloat(
            0.88f,
            1.12f,
            infiniteRepeatable(tween(1000, easing = FastOutSlowInEasing), RepeatMode.Reverse),
            label = "p1",
        )
    val pulse2 =
        transition.animateFloat(
            0.75f,
            1.25f,
            infiniteRepeatable(tween(1400, delayMillis = 200, easing = FastOutSlowInEasing), RepeatMode.Reverse),
            label = "p2",
        )
    val pulse3 =
        transition.animateFloat(
            0.65f,
            1.38f,
            infiniteRepeatable(tween(1800, delayMillis = 400, easing = FastOutSlowInEasing), RepeatMode.Reverse),
            label = "p3",
        )

    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .background(Color.Black),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.offset(y = (-48).dp),
        ) {
            Canvas(modifier = Modifier.size(200.dp)) {
                val base = 44.dp.toPx()
                drawCircle(NavyPrimary.copy(alpha = 0.12f), base * 2.2f * pulse3.value)
                drawCircle(NavyPrimary.copy(alpha = 0.22f), base * 1.75f * pulse2.value)
                drawCircle(NavyPrimary.copy(alpha = 0.38f), base * 1.35f * pulse1.value)
                drawCircle(NavyPrimary, base)
            }
            Spacer(Modifier.height(28.dp))
            Text(
                if (isSpeaking) "말하는 중..." else "듣는 중...",
                color = Color.White,
                fontSize = 18.sp,
                fontWeight = FontWeight.Medium,
            )
        }

        Row(
            modifier =
                Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 72.dp),
            horizontalArrangement = Arrangement.spacedBy(40.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier =
                    Modifier
                        .size(64.dp)
                        .clip(CircleShape)
                        .background(if (isMicOn) Color.White.copy(alpha = 0.15f) else HealthRed)
                        .clickable { isMicOn = !isMicOn },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (isMicOn) Icons.Default.Mic else Icons.Default.MicOff,
                    contentDescription = if (isMicOn) "마이크 끄기" else "마이크 켜기",
                    tint = Color.White,
                    modifier = Modifier.size(28.dp),
                )
            }

            Box(
                modifier =
                    Modifier
                        .size(64.dp)
                        .clip(CircleShape)
                        .background(HealthRed)
                        .clickable { onStop() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Default.CallEnd,
                    contentDescription = "종료",
                    tint = Color.White,
                    modifier = Modifier.size(28.dp),
                )
            }
        }
    }
}
