package com.example.mob

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.mob.common.AppDrawer
import com.example.mob.data.remote.RetrofitClient
import com.example.mob.feature.auth.LoginScreen
import com.example.mob.feature.chat.ChatScreen
import com.example.mob.feature.chat.ChatViewModel
import com.example.mob.feature.chat.VoiceCaptureOverlay
import com.example.mob.feature.health.HealthViewModel
import com.example.mob.feature.home.HomeScreen
import com.example.mob.feature.profile.ProfileScreen
import com.example.mob.ui.theme.DividerColor
import com.example.mob.ui.theme.MOBTheme
import com.example.mob.ui.theme.NavyPrimary
import com.example.mob.ui.theme.SurfaceWarm
import com.example.mob.ui.theme.SurfaceWhite
import com.example.mob.ui.theme.TextSecondary
import com.example.mob.voice.WakeWordForegroundService
import com.google.firebase.messaging.FirebaseMessaging
import com.kakao.sdk.common.KakaoSdk
import com.kakao.sdk.common.util.Utility
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private sealed class Screen(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    data object Chat : Screen("chat", "Chat", Icons.AutoMirrored.Filled.Chat)

    data object Home : Screen("home", "Home", Icons.Default.Home)

    data object Profile : Screen("profile", "Profile", Icons.Default.Person)
}

private val bottomNavScreens = listOf(Screen.Chat, Screen.Home, Screen.Profile)

class MainActivity : ComponentActivity() {
    // 웨이크 워드("젠트야") 감지 시 카운터를 증가시켜 Compose 트리에 신호를 전달.
    private val voiceWakeTrigger = mutableStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        KakaoSdk.init(this, getString(R.string.kakao_app_key))
        Log.d("KAKAO_KEY_HASH", Utility.getKeyHash(this))
        enableEdgeToEdge()
        handleWakeIntent(intent)
        setContent {
            MOBTheme {
                var splashDone by remember { mutableStateOf(false) }
                var isLoggedIn by remember { mutableStateOf(false) }
                WakeWordServicePermissionEffect()

                LaunchedEffect(Unit) {
                    delay(1800)
                    splashDone = true
                }

                when {
                    !splashDone -> SplashScreen()
                    !isLoggedIn -> LoginScreen(onLoginSuccess = { isLoggedIn = true })
                    else ->
                        MainApp(
                            onLogout = { isLoggedIn = false },
                            voiceWakeTrigger = voiceWakeTrigger.value,
                        )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleWakeIntent(intent)
    }

    private fun handleWakeIntent(intent: Intent?) {
        if (intent?.action == WakeWordForegroundService.ACTION_WAKE_WORD_DETECTED) {
            voiceWakeTrigger.value = voiceWakeTrigger.value + 1
            // 같은 인텐트가 회전 등으로 다시 들어와 더블 트리거되지 않도록 액션 소거
            intent.action = null
        }
    }
}

@Composable
private fun WakeWordServicePermissionEffect() {
    val context = LocalContext.current
    val permissions =
        remember {
            buildList {
                add(Manifest.permission.RECORD_AUDIO)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    add(Manifest.permission.POST_NOTIFICATIONS)
                }
            }.toTypedArray()
        }
    val permissionLauncher =
        rememberLauncherForActivityResult(
            contract = ActivityResultContracts.RequestMultiplePermissions(),
        ) { grants ->
            if (grants[Manifest.permission.RECORD_AUDIO] == true) {
                WakeWordForegroundService.start(context)
            }
        }

    LaunchedEffect(Unit) {
        val hasAudioPermission =
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.RECORD_AUDIO,
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED

        if (hasAudioPermission) {
            WakeWordForegroundService.start(context)
        } else {
            permissionLauncher.launch(permissions)
        }

        if (!Settings.canDrawOverlays(context)) {
            context.startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:${context.packageName}"),
                ),
            )
        }
    }
}

@Composable
private fun SplashScreen() {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .background(Color.Black),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "HEYGENT",
            color = Color.White,
            fontSize = 34.sp,
            fontWeight = FontWeight.ExtraBold,
            letterSpacing = 5.sp,
        )
    }
}

@Composable
private fun MainApp(
    onLogout: () -> Unit,
    voiceWakeTrigger: Int,
) {
    val context = LocalContext.current
    val healthViewModel = remember { HealthViewModel(context) }

    val chatViewModel = remember { ChatViewModel() }
    val navController = rememberNavController()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    // 토큰 만료 시 자동 로그아웃
    LaunchedEffect(Unit) {
        RetrofitClient.sessionExpiredEvent.collect { onLogout() }
    }

    // FCM 토큰 등록 (앱 시작 시 1회)
    LaunchedEffect(Unit) {
        FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
            Log.d("FCM", "토큰 등록 요청: ${token.take(20)}...")
            chatViewModel.registerFcmToken(token)
        }
    }

    // 주기적 동기화 시작
    LaunchedEffect(Unit) {
        healthViewModel.startPeriodicSync()
        // 권한이 없으면 요청 (최초 1회)
        if (!healthViewModel.syncState.value.let { it is HealthViewModel.HealthSyncState.Success }) {
            (context as? Activity)?.let { healthViewModel.requestPermissions(it) }
        }
    }

    // 앱 세션 동안 유지 (앱 재실행 시 초기화됨)
    var activeChatSessionId by remember { mutableStateOf<String?>(null) }
    var agentName by remember { mutableStateOf("HeyGent") }
    var voiceOverlayVisible by remember { mutableStateOf(false) }

    val openVoiceOverlay: () -> Unit = { voiceOverlayVisible = true }

    // "젠트야" 호출 감지 → 가장 최근 채팅 세션으로 이동 + 오버레이 자동 노출
    LaunchedEffect(voiceWakeTrigger) {
        if (voiceWakeTrigger == 0) return@LaunchedEffect

        val cached = chatViewModel.sessions.value
        val targetId =
            if (cached.isNotEmpty()) {
                cached.first().sessionId
            } else {
                chatViewModel.loadSessionsSuspend().firstOrNull()?.sessionId
            }

        // 세션이 있으면 그 세션으로, 없으면 새 세션
        activeChatSessionId = targetId ?: ""
        navController.navigate(Screen.Chat.route) { launchSingleTop = true }
        voiceOverlayVisible = true
    }

    Box(modifier = Modifier.fillMaxSize()) {
        ModalNavigationDrawer(
            drawerState = drawerState,
            drawerContent = {
                AppDrawer(
                    onClose = { scope.launch { drawerState.close() } },
                    agentName = agentName,
                    sessions = chatViewModel.sessions.collectAsState().value,
                    onNewChat = {
                        activeChatSessionId = ""
                        navController.navigate(Screen.Chat.route) { launchSingleTop = true }
                        scope.launch { drawerState.close() }
                    },
                    onHistoryItemClick = { sessionId ->
                        activeChatSessionId = sessionId
                        navController.navigate(Screen.Chat.route) { launchSingleTop = true }
                        scope.launch { drawerState.close() }
                    },
                )
            },
        ) {
            Scaffold(
                bottomBar = { AppBottomBar(navController) },
            ) { innerPadding ->
                val bottomPadding = innerPadding.calculateBottomPadding()
                val onMenuClick: () -> Unit = { scope.launch { drawerState.open() } }

                NavHost(
                    navController = navController,
                    startDestination = Screen.Home.route,
                    enterTransition = { EnterTransition.None },
                    exitTransition = { ExitTransition.None },
                    popEnterTransition = { EnterTransition.None },
                    popExitTransition = { ExitTransition.None },
                ) {
                    composable(Screen.Chat.route) {
                        ChatScreen(
                            onMenuClick = onMenuClick,
                            activeChatSessionId = activeChatSessionId,
                            onActiveChatSessionChange = { activeChatSessionId = it },
                            viewModel = chatViewModel,
                            agentName = agentName,
                            bottomPadding = bottomPadding,
                            onVoiceMode = openVoiceOverlay,
                        )
                    }
                    composable(Screen.Home.route) {
                        HomeScreen(
                            onMenuClick = onMenuClick,
                            bottomPadding = bottomPadding,
                        )
                    }
                    composable(Screen.Profile.route) {
                        ProfileScreen(
                            onMenuClick = onMenuClick,
                            bottomPadding = bottomPadding,
                            onLogout = onLogout,
                            agentName = agentName,
                            onAgentNameChange = { agentName = it },
                            healthViewModel = healthViewModel,
                        )
                    }
                }
            }
        }

        if (voiceOverlayVisible) {
            val systemBottomInset =
                WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
            VoiceCaptureOverlay(
                bottomInset = systemBottomInset,
                onSend = { text ->
                    voiceOverlayVisible = false
                    chatViewModel.sendMessage(text)
                },
                onCancel = { voiceOverlayVisible = false },
            )
        }
    }
}

@Composable
private fun AppBottomBar(navController: NavHostController) {
    val currentRoute =
        navController
            .currentBackStackEntryAsState()
            .value
            ?.destination
            ?.route

    val selectedIndex =
        bottomNavScreens
            .indexOfFirst { it.route == currentRoute }
            .let { if (it == -1) 0 else it }

    val animatedIndex by animateFloatAsState(
        targetValue = selectedIndex.toFloat(),
        animationSpec = spring(dampingRatio = 0.8f, stiffness = 500f),
        label = "nav_indicator",
    )

    Column {
        HorizontalDivider(color = DividerColor, thickness = 0.5.dp)
        BoxWithConstraints(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(56.dp)
                    .background(SurfaceWhite),
        ) {
            val itemWidth = maxWidth / bottomNavScreens.size

            // 슬라이딩 선택 인디케이터 (아이콘+글자 전체 포함)
            Box(
                modifier =
                    Modifier
                        .offset(x = itemWidth * animatedIndex + 8.dp)
                        .width(itemWidth - 16.dp)
                        .fillMaxHeight()
                        .padding(vertical = 5.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(SurfaceWarm),
            )

            Row(modifier = Modifier.fillMaxSize()) {
                bottomNavScreens.forEach { screen ->
                    val selected = currentRoute == screen.route
                    Column(
                        modifier =
                            Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .clickable(
                                    interactionSource = remember { MutableInteractionSource() },
                                    indication = null,
                                ) {
                                    navController.navigate(screen.route) {
                                        popUpTo(Screen.Home.route) { inclusive = false }
                                        launchSingleTop = true
                                    }
                                },
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Icon(
                            screen.icon,
                            contentDescription = screen.label,
                            tint = if (selected) NavyPrimary else TextSecondary,
                            modifier = Modifier.size(22.dp),
                        )
                        Spacer(Modifier.height(1.dp))
                        Text(
                            screen.label,
                            fontSize = 10.sp,
                            color = if (selected) NavyPrimary else TextSecondary,
                        )
                    }
                }
            }
        }
        // 갤럭시 시스템 네비게이션 바 영역 — 불투명 흰 배경으로 채움
        Spacer(
            modifier =
                Modifier
                    .background(Color.White)
                    .fillMaxWidth()
                    .navigationBarsPadding(),
        )
    }
}
