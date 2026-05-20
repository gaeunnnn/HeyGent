"""브릿지 측 도구 실행기.

AI 서버에서 받은 tool.invoke 메시지를 사용자 PC 의 AppContainer 워커 안에서 실행하고,
LocalToolRuntime 과 동일한 형식의 결과 dict 를 만들어 돌려준다.

설계:
  - 본체는 본 모듈만 호출. 본체는 AppContainer 밖이라 토큰 저장소 등 사용자 자원에 자유롭게 접근 가능하다.
  - 본 모듈은 bridge.sandbox 의 워커를 띄우고 파이프로 명령을 위임한다.
  - 워커는 AppContainer 안에 있어 워크스페이스 폴더만 접근 가능 → 모든 도구 호출이 OS 단에서 일관 격리된다.
  - 워커가 죽거나 hang 하면 재기동한다. 첫 호출에서 워커 spawn 이 실패하면 대안 폴백으로
    본체 안에서 직접 실행 (sandbox.launch_worker 가 폴백 모드 핸들을 반환하므로 동일 코드 경로).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from bridge import sandbox


logger = logging.getLogger("bridge.executor")


_worker: sandbox.WorkerHandle | None = None
_worker_workspace: Path | None = None
_worker_lock = threading.Lock()


SUPPORTED_TOOLS = ("terminal.run", "read_file", "write_file", "patch", "search_files")


def execute_tool(*, name: str, args: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    """이름에 맞는 도구를 워커에 위임해 실행한다. 알 수 없는 도구면 에러 dict 반환."""

    if name not in SUPPORTED_TOOLS:
        return _tool_error(
            code="bridge_tool_not_supported",
            message=f"브릿지가 아직 지원하지 않는 도구입니다: {name}",
            tool_name=name,
        )

    # 모델이 보낸 workspace_root 는 절대 신뢰하지 않는다 — 페어링 시 브릿지가 정한 root 만 쓴다.
    trusted_args = dict(args)
    trusted_args["workspace_root"] = str(workspace_root)

    try:
        worker = _get_worker(workspace_root)
    except Exception as exc:
        logger.exception("워커 spawn 실패")
        return _tool_error(
            code="bridge_worker_spawn_failed",
            message=f"{type(exc).__name__}: {exc}",
            tool_name=name,
        )

    request = {"id": uuid.uuid4().hex, "cmd": name, "args": trusted_args}
    try:
        response = worker.call(request)
    except (TimeoutError, OSError) as exc:
        # 워커가 막혔거나 죽었다. 강제 종료 후 재기동을 다음 호출에서 시도한다.
        logger.warning("워커 호출 실패 (재기동 예정): %s", exc)
        _kill_worker()
        return _tool_error(
            code="bridge_worker_unavailable",
            message=f"{type(exc).__name__}: {exc}",
            tool_name=name,
        )
    except Exception as exc:
        logger.exception("워커 호출 중 예외")
        return _tool_error(
            code="bridge_worker_failed",
            message=f"{type(exc).__name__}: {exc}",
            tool_name=name,
        )

    return _format_response(name=name, response=response)


def _format_response(*, name: str, response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok"):
        result = response.get("result")
        if not isinstance(result, dict):
            return _tool_error(
                code="bridge_worker_bad_response",
                message="worker returned non-dict result",
                tool_name=name,
            )
        return result

    error = response.get("error") or {}
    code = str(error.get("code") or "bridge_worker_error")
    message = str(error.get("message") or "unknown worker error")
    payload = {
        "error": {
            "code": code,
            "message": message,
            "tool_name": name,
        }
    }
    return {
        "ok": False,
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def _tool_error(*, code: str, message: str, tool_name: str) -> dict[str, Any]:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "tool_name": tool_name,
        }
    }
    return {
        "ok": False,
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }


# --- 워커 수명주기 -----------------------------------------------------------


def _get_worker(workspace_root: Path) -> sandbox.WorkerHandle:
    """워커 핸들을 돌려준다. 없거나 죽었거나 워크스페이스가 바뀌었으면 새로 띄운다."""

    global _worker, _worker_workspace
    with _worker_lock:
        needs_spawn = (
            _worker is None
            or _worker.dead
            or _worker_workspace != workspace_root
        )
        if needs_spawn:
            if _worker is not None:
                try:
                    _worker.terminate()
                except Exception:
                    logger.exception("기존 워커 종료 중 오류 (무시)")
            argv = _resolve_worker_argv(workspace_root)
            logger.info("워커 spawn argv=%s cwd=%s", argv, workspace_root)
            _worker = sandbox.launch_worker(workspace_root=workspace_root, worker_argv=argv)
            _worker_workspace = workspace_root
            logger.info(
                "워커 준비 완료 pid=%s sandboxed=%s",
                _worker.pid,
                _worker.sandboxed,
            )
        return _worker


def _kill_worker() -> None:
    global _worker, _worker_workspace
    with _worker_lock:
        if _worker is not None:
            try:
                _worker.terminate()
            except Exception:
                logger.exception("워커 강제 종료 중 오류 (무시)")
        _worker = None
        _worker_workspace = None


def shutdown_worker() -> None:
    """브릿지 종료 시 호출. 워커 프로세스가 떠도 남지 않게 정리."""

    _kill_worker()


def worker_status() -> dict[str, Any]:
    """발표/UI 디버그용 워커 상태."""

    with _worker_lock:
        if _worker is None:
            return {"running": False, "pid": None, "sandboxed": None}
        return {
            "running": not _worker.dead,
            "pid": _worker.pid,
            "sandboxed": _worker.sandboxed,
            "workspace_root": str(_worker_workspace) if _worker_workspace else None,
        }


def _sandbox_runtime_dir() -> Path:
    """AppContainer 워커 .exe 와 stderr 로그를 둘 곳. 사용자 워크스페이스를 더럽히지 않는다.

    Windows: %LOCALAPPDATA%\\HeyGent\\sandbox
    이 폴더는 우리가 ACL 로 AppContainer SID 에 권한을 부여해 워커가 자기 .exe 를 실행하고
    stderr 를 쓸 수 있도록 한다. 워크스페이스와는 완전히 분리.
    """

    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "HeyGent" / "sandbox"


def _resolve_worker_argv(workspace_root: Path) -> list[str]:
    """워커 entrypoint argv 를 결정한다.

    1) PyInstaller 빌드본 (frozen): HeyGentBridge.exe 를 %LOCALAPPDATA%\\HeyGent\\sandbox\\
       에 복사한 뒤 그 사본을 --sandbox-worker 모드로 띄운다. 사용자 워크스페이스 안에 .exe
       파일을 두지 않아 워크스페이스 listing 이 깨끗하다. sandbox 폴더는 우리가 ACL 명시 통제.
    2) 개발 실행: 같은 인터프리터로 sandbox_worker.py 실행 (sandboxed=False 폴백).
    """

    if getattr(sys, "frozen", False):
        runtime_dir = _sandbox_runtime_dir()
        worker_exe = runtime_dir / "worker.exe"
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True)
            _ensure_exe_copy(src=Path(sys.executable), dst=worker_exe)
            return [str(worker_exe), "--sandbox-worker"]
        except Exception:
            logger.exception(
                ".exe 사본 준비 실패. 원본 위치(%s) 로 fallback (격리 미동작 가능).",
                sys.executable,
            )
            return [sys.executable, "--sandbox-worker"]

    worker_script = Path(__file__).resolve().parent / "sandbox_worker.py"
    return [sys.executable, str(worker_script)]


def _ensure_exe_copy(*, src: Path, dst: Path) -> None:
    """src 와 dst 사이즈가 같으면 그대로 둠. 다르면 복사. 첫 spawn 1회만 비용."""

    try:
        if dst.exists() and src.stat().st_size == dst.stat().st_size:
            return
    except OSError:
        pass
    import shutil
    shutil.copy2(src, dst)
