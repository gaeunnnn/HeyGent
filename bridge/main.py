"""HeyGent 로컬 브릿지 PoC 단계 1 진입점.

이 단계의 목표는 단순하다:
  1. AI 서버에 WebSocket으로 접속한다.
  2. bridge.hello 메시지로 인증 토큰을 보낸다.
  3. bridge.ack를 받으면 "연결 성공" 메시지를 콘솔에 띄운다.
  4. 주기적으로 ping을 보내 연결이 살아있음을 알린다.
  5. 끊기면 잠시 기다렸다가 재연결한다.

도구 위임(tool.invoke) 처리는 단계 2에서 추가한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import ssl
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from bridge.config import BridgeSettings, load_settings
from bridge.executor import execute_tool


logger = logging.getLogger("bridge")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # websockets 라이브러리 로그는 너무 시끄러우므로 INFO로 낮춘다.
    logging.getLogger("websockets").setLevel(logging.INFO)


async def _send_json(websocket: websockets.WebSocketClientProtocol, payload: dict[str, Any]) -> None:
    await websocket.send(json.dumps(payload, ensure_ascii=False))


async def _recv_json(websocket: websockets.WebSocketClientProtocol) -> dict[str, Any] | None:
    raw = await websocket.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    logger.debug("raw recv: %s", raw[:300])
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AI 서버에서 JSON이 아닌 메시지를 받았습니다: %s", raw[:200])
        return None
    return parsed if isinstance(parsed, dict) else None


async def _ping_loop(websocket: websockets.WebSocketClientProtocol, interval_seconds: float) -> None:
    """주기적으로 application-level ping을 보내 연결을 유지한다."""

    while True:
        await asyncio.sleep(interval_seconds)
        await _send_json(websocket, {"type": "ping"})


async def _handle_tool_invoke(
    websocket: websockets.WebSocketClientProtocol,
    *,
    settings: BridgeSettings,
    message: dict[str, Any],
) -> None:
    """AI 서버에서 받은 tool.invoke를 사용자 PC에서 실행하고 결과를 돌려준다.

    실행 자체는 동기 subprocess를 쓰지만, WebSocket 수신 루프를 막지 않도록
    실제 실행은 to_thread로 별도 스레드에 던진다. 단계 2 단순 명령(whoami 등)에는
    이 정도 구조로 충분하고, 단계 4(진행 상황 스트리밍)에서 더 정교하게 다룬다.
    """

    call_id = str(message.get("call_id") or "").strip()
    name = str(message.get("name") or "").strip()
    args = message.get("args") if isinstance(message.get("args"), dict) else {}

    if not call_id or not name:
        logger.warning("tool.invoke 형식이 올바르지 않습니다: %s", message)
        return

    logger.info("도구 실행 요청 수신: name=%s call_id=%s", name, call_id)

    try:
        result = await asyncio.to_thread(
            execute_tool,
            name=name,
            args=args,
            workspace_root=settings.workspace_root,
        )
    except Exception as exc:
        logger.exception("도구 실행 중 예외")
        result = {
            "ok": False,
            "error": {
                "code": "bridge_executor_exception",
                "message": f"{type(exc).__name__}: {exc}",
                "tool_name": name,
            },
        }

    await _send_json(
        websocket,
        {
            "type": "tool.result",
            "call_id": call_id,
            "result": result,
        },
    )
    logger.info("도구 실행 결과 전송 완료: name=%s call_id=%s", name, call_id)


async def _receive_loop(
    websocket: websockets.WebSocketClientProtocol,
    *,
    settings: BridgeSettings,
) -> None:
    """AI 서버에서 오는 메시지를 받아 분기 처리한다."""

    while True:
        message = await _recv_json(websocket)
        if message is None:
            continue
        message_type = message.get("type")
        if message_type == "pong":
            logger.debug("pong 수신")
            continue
        if message_type == "bridge.error":
            logger.error("AI 서버에서 오류 응답: %s", message.get("reason"))
            continue
        if message_type == "tool.invoke":
            # 도구 실행은 시간이 걸릴 수 있으므로 별도 task로 띄워 수신 루프를 막지 않는다.
            asyncio.create_task(_handle_tool_invoke(websocket, settings=settings, message=message))
            continue
        logger.info("AI 서버 메시지 수신: type=%s", message_type)


async def _run_session(
    settings: BridgeSettings,
    *,
    on_connected: Any = None,
    on_disconnected: Any = None,
) -> None:
    """한 번의 연결 세션을 처리한다. 끊기면 호출자가 재시도를 결정한다.

    on_connected/on_disconnected 콜백은 트레이 아이콘 같은 UI가 상태를 갱신할 때 사용한다.
    콘솔 모드(bridge/main.py 직접 실행)에서는 None으로 호출된다.
    """

    if not settings.token:
        logger.error("브릿지 토큰이 없습니다. GUI 에서 페어링을 먼저 진행해주세요.")
        return
    if settings.workspace_root is None:
        logger.error("워크스페이스 폴더가 선택되지 않았습니다. GUI 에서 폴더를 먼저 지정해주세요.")
        return

    logger.info("AI 서버에 접속 시도: %s", settings.ai_ws_url)
    # WebSocket 프로토콜 레벨의 keep-alive를 켠다. application-level ping과 별개로
    # docker NAT/프록시가 idle 연결로 판정해 끊는 것을 방지한다.
    ssl_context: ssl.SSLContext | None = None
    if settings.ai_ws_url.lower().startswith("wss://"):
        # 기본 시스템 루트 CA 로 검증. NPM/Let's Encrypt 같은 표준 인증서는 그대로 통과.
        ssl_context = ssl.create_default_context()

    try:
        async with websockets.connect(
            settings.ai_ws_url,
            ping_interval=settings.ping_interval_seconds,
            ping_timeout=settings.ping_interval_seconds,
            ssl=ssl_context,
        ) as websocket:
            # 1. hello 전송
            await _send_json(
                websocket,
                {
                    "type": "bridge.hello",
                    "token": settings.token,
                    "workspace_root": str(settings.workspace_root),
                    "device_name": settings.device_name or "",
                },
            )

            # 2. ack 또는 error 대기
            first_response = await _recv_json(websocket)
            if first_response is None or first_response.get("type") != "bridge.ack":
                reason = (first_response or {}).get("reason") if first_response else "no_response"
                logger.error("AI 서버 인증 실패: %s", reason)
                return

            logger.info(
                "AI 서버 연결됨 (session_id=%s, workspace=%s)",
                first_response.get("session_id"),
                settings.workspace_root,
            )
            if on_connected is not None:
                try:
                    on_connected()
                except Exception:
                    logger.exception("on_connected 콜백에서 예외")

            # 3. ping 루프와 수신 루프를 동시에 돌린다.
            ping_task = asyncio.create_task(_ping_loop(websocket, settings.ping_interval_seconds))
            receive_task = asyncio.create_task(_receive_loop(websocket, settings=settings))
            try:
                done, pending = await asyncio.wait(
                    {ping_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    exc = task.exception()
                    if exc is not None and not isinstance(exc, ConnectionClosed):
                        raise exc
            finally:
                ping_task.cancel()
                receive_task.cancel()
    finally:
        if on_disconnected is not None:
            try:
                on_disconnected()
            except Exception:
                logger.exception("on_disconnected 콜백에서 예외")


async def _main() -> None:
    _configure_logging()
    settings = load_settings()

    logger.info("브릿지 시작. workspace_root=%s", settings.workspace_root)

    stop_event = asyncio.Event()

    def _request_stop(*_args: Any) -> None:
        logger.info("종료 시그널 감지, 브릿지를 닫습니다.")
        stop_event.set()

    # SIGINT(Ctrl+C)와 SIGTERM에서 깔끔하게 종료한다.
    # Windows는 SIGTERM이 없는 환경이 있을 수 있어 try/except로 감싼다.
    try:
        signal.signal(signal.SIGINT, _request_stop)
    except ValueError:
        pass
    try:
        signal.signal(signal.SIGTERM, _request_stop)
    except (AttributeError, ValueError):
        pass

    while not stop_event.is_set():
        try:
            await _run_session(settings)
        except (ConnectionClosed, OSError) as exc:
            logger.warning("연결 끊김: %s", exc)
        except Exception:
            logger.exception("세션 처리 중 예외")

        if stop_event.is_set():
            break

        logger.info("%.1f초 후 재연결합니다.", settings.reconnect_delay_seconds)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.reconnect_delay_seconds)
        except asyncio.TimeoutError:
            pass


def main() -> None:
    # 콘솔 모드에서도 --sandbox-worker 분기는 동일하게 동작해야 한다.
    import sys
    if "--sandbox-worker" in sys.argv[1:]:
        from bridge import sandbox_worker
        sys.exit(sandbox_worker.main())
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
