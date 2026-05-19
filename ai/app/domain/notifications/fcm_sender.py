from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# firebase-admin 패키지가 없으면 FCM 기능 비활성화
try:
    import firebase_admin
    from firebase_admin import credentials, messaging

    _app: firebase_admin.App | None = None

    def _get_app() -> firebase_admin.App | None:
        global _app
        if _app is not None:
            return _app
        try:
            _app = firebase_admin.get_app()
            return _app
        except ValueError:
            pass

        cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")
        if not cred_path:
            logger.warning(
                "FIREBASE_CREDENTIALS_PATH 환경변수가 설정되지 않아 FCM 알림을 보낼 수 없습니다."
            )
            return None

        try:
            cred = credentials.Certificate(cred_path)
            _app = firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK 초기화 완료")
            return _app
        except Exception as e:
            logger.error(f"Firebase 초기화 실패: {e}")
            return None

    def send_chat_notification(
        fcm_token: str,
        *,
        session_id: str,
        content: str,
        title: str = "HeyGent 응답",
    ) -> None:
        """AI 응답 완료 시 모바일 앱에 FCM 푸시 알림을 전송한다."""
        app = _get_app()
        if app is None:
            return

        preview = content[:100] + ("..." if len(content) > 100 else "")
        try:
            msg = messaging.Message(
                notification=messaging.Notification(title=title, body=preview),
                data={"sessionId": session_id},
                token=fcm_token,
                android=messaging.AndroidConfig(priority="high"),
            )
            result = messaging.send(msg)
            logger.info(f"FCM 발송 성공: messageId={result} session={session_id}")
        except Exception as e:
            logger.warning(f"FCM 발송 실패 (무시): {e}")

except ImportError:
    logger.info(
        "firebase-admin 패키지 없음 — FCM 알림 비활성화 "
        "(활성화하려면: pip install firebase-admin)"
    )

    def send_chat_notification(
        fcm_token: str,
        *,
        session_id: str,
        content: str,
        title: str = "HeyGent 응답",
    ) -> None:
        pass
