package com.example.mob.feature.chat

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.mob.data.remote.ChatSessionMessageResponse
import com.example.mob.data.remote.ChatSessionResponse
import com.example.mob.data.remote.ChatWebSocketClient
import com.example.mob.data.remote.RetrofitClient
import com.example.mob.data.remote.SendChatMessageRequest
import com.example.mob.data.remote.WsTaskEvent
import com.example.mob.fcm.FcmEventBus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class ChatViewModel : ViewModel() {

    // ─── 상태 ─────────────────────────────────────────────────────────────────

    private val _sessions = MutableStateFlow<List<ChatSessionResponse>>(emptyList())
    val sessions: StateFlow<List<ChatSessionResponse>> = _sessions.asStateFlow()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages.asStateFlow()

    private val _isLoadingSessions = MutableStateFlow(false)
    val isLoadingSessions: StateFlow<Boolean> = _isLoadingSessions.asStateFlow()

    private val _isProcessing = MutableStateFlow(false)
    val isProcessing: StateFlow<Boolean> = _isProcessing.asStateFlow()

    private val _activeSessionId = MutableStateFlow<String?>(null)
    val activeSessionId: StateFlow<String?> = _activeSessionId.asStateFlow()

    val currentSessionTitle: StateFlow<String> = combine(_activeSessionId, _sessions) { id, list ->
        if (id.isNullOrEmpty()) "새 세션"
        else list.firstOrNull { it.sessionId == id }?.title?.takeIf { it.isNotBlank() } ?: "새 세션"
    }.stateIn(viewModelScope, SharingStarted.Eagerly, "새 세션")

    // ─── WebSocket ────────────────────────────────────────────────────────────

    private val wsClient = ChatWebSocketClient()

    /** 현재 AI가 처리 중인 태스크 (WAITING 상태일 때만 세팅) */
    private var pendingTaskRunId: String? = null
    private var pendingSessionId: String? = null

    init {
        // 태스크 이벤트 수신 루프
        viewModelScope.launch {
            wsClient.events.collect { event -> onTaskEvent(event) }
        }
        // FCM 수신 시 현재 세션 메시지 갱신
        viewModelScope.launch {
            FcmEventBus.sessionRefreshEvent.collect { sessionId ->
                val target = sessionId ?: _activeSessionId.value ?: return@collect
                Log.d("ChatViewModel", "FCM 수신 → 메시지 갱신: sessionId=$target")
                try {
                    val resp = RetrofitClient.aiApiService.getChatSessionMessages(target)
                    _messages.value = resp.items.mapNotNull { it.toChatMessage() }
                    // FCM = AI 처리 완료 신호이므로 pending 상태 초기화
                    pendingTaskRunId = null
                    pendingSessionId = null
                    _isProcessing.value = false
                    loadSessions()
                } catch (e: Exception) {
                    Log.e("ChatViewModel", "FCM 갱신 실패: ${e.message}", e)
                }
            }
        }
    }

    override fun onCleared() {
        wsClient.disconnect()
        super.onCleared()
    }

    // ─── 세션 관리 ────────────────────────────────────────────────────────────

    fun loadSessions() {
        viewModelScope.launch { loadSessionsSuspend() }
    }

    /** 세션 목록을 동기적으로 로드하고 반환한다 (호출자가 결과를 즉시 필요로 할 때) */
    suspend fun loadSessionsSuspend(): List<ChatSessionResponse> {
        _isLoadingSessions.value = true
        return try {
            val resp = RetrofitClient.aiApiService.getChatSessions()
            _sessions.value = resp.items
            resp.items
        } catch (e: Exception) {
            Log.e("ChatViewModel", "loadSessions 실패: ${e.javaClass.simpleName} ${e.message}", e)
            emptyList()
        } finally {
            _isLoadingSessions.value = false
        }
    }

    fun openSession(sessionId: String) {
        _activeSessionId.value = sessionId
        _messages.value = emptyList()
        viewModelScope.launch {
            try {
                val resp = RetrofitClient.aiApiService.getChatSessionMessages(sessionId)
                _messages.value = resp.items.mapNotNull { it.toChatMessage() }
            } catch (e: Exception) {
                Log.e("ChatViewModel", "openSession 실패: ${e.javaClass.simpleName} ${e.message}", e)
            }
        }
    }

    fun startNewSession() {
        _activeSessionId.value = null
        _messages.value = emptyList()
    }

    // ─── 메시지 전송 ──────────────────────────────────────────────────────────

    fun sendMessage(content: String) {
        val currentSessionId = _activeSessionId.value
        viewModelScope.launch {
            _isProcessing.value = true
            _messages.value = _messages.value + ChatMessage(
                isBot = false, text = content, timestamp = nowFormatted()
            )
            try {
                val request = SendChatMessageRequest(content = content, sessionId = currentSessionId)
                val resp = if (currentSessionId != null) {
                    RetrofitClient.aiApiService.sendChatMessage(currentSessionId, request)
                } else {
                    RetrofitClient.aiApiService.sendChatMessageNewSession(request)
                }

                if (_activeSessionId.value == null) _activeSessionId.value = resp.sessionId

                if (resp.assistantMessage != null) {
                    // ── 즉시 완료 (COMPLETED) ─────────────────────────────
                    // append 대신 API에서 재조회: FCM과의 race condition으로 인한 중복 방지
                    val msgResp = RetrofitClient.aiApiService.getChatSessionMessages(resp.sessionId)
                    _messages.value = msgResp.items.mapNotNull { it.toChatMessage() }
                    _isProcessing.value = false
                    loadSessions()
                } else {
                    // ── 비동기 처리 중 (WAITING/RUNNING) ─────────────────
                    // WebSocket으로 태스크 완료 이벤트를 기다린다
                    Log.d("ChatViewModel", "태스크 WAITING: taskRunId=${resp.taskRunId}, status=${resp.status}")
                    pendingTaskRunId = resp.taskRunId
                    pendingSessionId = resp.sessionId

                    val token = RetrofitClient.getAccessToken()
                    if (token.isNotBlank()) {
                        if (!wsClient.isConnected()) wsClient.connect(token)
                        wsClient.subscribeTask(resp.taskRunId)
                    } else {
                        Log.w("ChatViewModel", "액세스 토큰 없음 — WS 구독 불가")
                        _isProcessing.value = false
                    }
                }
            } catch (e: Exception) {
                Log.e("ChatViewModel", "sendMessage 실패: ${e.javaClass.simpleName} ${e.message}", e)
                _isProcessing.value = false
            }
        }
    }

    fun stopProcessing() {
        pendingTaskRunId = null
        pendingSessionId = null
        _isProcessing.value = false
    }

    // ─── FCM 토큰 등록 ────────────────────────────────────────────────────────

    fun registerFcmToken(token: String) {
        viewModelScope.launch {
            try {
                RetrofitClient.aiApiService.registerFcmToken(mapOf("token" to token))
                Log.d("ChatViewModel", "FCM 토큰 등록 성공")
            } catch (e: Exception) {
                Log.w("ChatViewModel", "FCM 토큰 등록 실패 (무시): ${e.message}")
            }
        }
    }

    // ─── WS 이벤트 처리 ───────────────────────────────────────────────────────

    private fun onTaskEvent(event: WsTaskEvent) {
        val taskRunId = pendingTaskRunId ?: return
        if (event.taskRunId != taskRunId) return

        val type = event.type.lowercase()
        val status = event.raw.optString("status").uppercase()
        val payloadStatus = event.raw.optJSONObject("payload")
            ?.optString("status")?.uppercase() ?: ""

        val isTerminal = type.contains("complet") || type.contains("finish") ||
                status in setOf("COMPLETED", "FAILED", "ERROR") ||
                payloadStatus in setOf("COMPLETED", "FAILED", "ERROR")

        Log.d("ChatViewModel", "WS 태스크 이벤트: type=$type status=$status isTerminal=$isTerminal")

        if (isTerminal) {
            val sessionId = pendingSessionId ?: _activeSessionId.value ?: return
            pendingTaskRunId = null
            pendingSessionId = null

            viewModelScope.launch {
                try {
                    // 최신 메시지 목록을 HTTP로 다시 조회
                    val resp = RetrofitClient.aiApiService.getChatSessionMessages(sessionId)
                    _messages.value = resp.items.mapNotNull { it.toChatMessage() }
                    loadSessions()
                } catch (e: Exception) {
                    Log.e("ChatViewModel", "WS 완료 후 메시지 갱신 실패: ${e.message}", e)
                } finally {
                    _isProcessing.value = false
                }
            }
        }
    }
}

// ─── 유틸 ─────────────────────────────────────────────────────────────────────

private fun nowFormatted() = SimpleDateFormat("a\nhh:mm", Locale.KOREAN).format(Date())

private fun ChatSessionMessageResponse.toChatMessage(): ChatMessage? {
    val text = content?.takeIf { it.isNotEmpty() } ?: return null
    val time = try {
        val millis = java.time.OffsetDateTime.parse(timestamp).toInstant().toEpochMilli()
        SimpleDateFormat("a\nhh:mm", Locale.KOREAN).format(Date(millis))
    } catch (_: Exception) { timestamp ?: "" }
    return ChatMessage(isBot = role == "assistant", text = text, timestamp = time)
}

fun ChatSessionResponse.formatTime(): String {
    val ts = updatedAt ?: createdAt ?: return ""
    return try {
        val millis = java.time.OffsetDateTime.parse(ts).toInstant().toEpochMilli()
        val msgDate = Date(millis)
        val cal = Calendar.getInstance().apply { time = msgDate }
        val now = Calendar.getInstance()
        when {
            cal[Calendar.YEAR] == now[Calendar.YEAR] &&
                    cal[Calendar.DAY_OF_YEAR] == now[Calendar.DAY_OF_YEAR] ->
                SimpleDateFormat("a h:mm", Locale.KOREAN).format(msgDate)
            cal[Calendar.YEAR] == now[Calendar.YEAR] &&
                    now[Calendar.DAY_OF_YEAR] - cal[Calendar.DAY_OF_YEAR] == 1 -> "어제"
            else -> SimpleDateFormat("M월 d일", Locale.KOREAN).format(msgDate)
        }
    } catch (_: Exception) { "" }
}
