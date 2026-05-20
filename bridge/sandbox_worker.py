"""AppContainer 안에서 도는 워커 진입점.

브릿지 본체가 표준입출력 파이프로 JSON 요청을 보내면 받아서 처리하고 JSON 응답을 한 줄
돌려준다. 워커는 격리되어 있어서:
  - 워크스페이스 폴더 밖 파일 read/write 시도 → 윈도우가 PermissionError 발생
  - 외부 네트워크 접근 → capability 없음 → OS 가 차단
  - AppData (페어링 토큰 저장소) → ACL 에 없어서 거부

본체에서 보낸 args.workspace_root 는 그대로 신뢰한다 — 같은 머신 같은 사용자 권한이 띄운
파이프 부모 자식 관계라 외부에서 끼어들 수 없다.

I/O 프로토콜:
  요청:  {"id": "...", "cmd": "terminal.run", "args": {...}}\n
  응답:  {"id": "...", "ok": true,  "result": {...}}\n
         {"id": "...", "ok": false, "error": {"code": "...", "message": "..."}}\n
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any


# bridge/_file_tools.py 와 같은 로직을 재사용한다. PyInstaller 빌드본에서는 같은 .exe 안에
# 묶이지만, 워커는 별도 .exe 라 sys.path 가 다르다. 그래서 같은 폴더의 _file_tools.py 를 import
# 가능하도록 진입 시점에 보강한다.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))


def _load_file_tools():
    try:
        from bridge import _file_tools  # type: ignore[import-not-found]
        return _file_tools
    except Exception:
        import _file_tools  # type: ignore[no-redef]
        return _file_tools


MAX_TERMINAL_STREAM_CHARS = 12_000

BLOCKED_PATTERNS = (
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*[fd][a-z]*\b",
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/|\\|[a-z]:\\|\*|\.)(\s|$)",
    r"\bdel\s+/(s|q)\b",
    r"\brmdir\s+/(s|q)\b",
    r"\bremove-item\b\s+\.\s+.*-force\b.*-recurse\b",
    r"\bremove-item\b\s+\.\s+.*-recurse\b.*-force\b",
    r"\bmkfs(\.| )",
    r"\bformat\s+[a-z]:",
)


def main() -> int:
    # AppContainer 안에서는 stdout 의 라인 버퍼링이 fully buffered 가 되기 쉽다 → 명령마다 flush.
    # 또한 PyInstaller frozen 모드에서 sys.stdout 의 기본 인코딩이 cp949 (한국어 윈도우) 라
    # JSON 응답에 비-cp949 문자가 들어가면 UnicodeEncodeError 가 나기 때문에 utf-8 로 강제.
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True, errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True, errors="replace")

    # AppContainer 자식은 lpCurrentDirectory 가 워크스페이스로 설정돼도 권한 부족이면 C:\ 로
    # fallback 한다. 명시적으로 chdir 하면 cmd/PowerShell 자식들도 올바른 cwd 에서 실행된다.
    workspace = os.environ.get("HEYGENT_BRIDGE_WORKSPACE")
    if workspace:
        try:
            os.chdir(workspace)
        except OSError:
            pass

    stdin_buf = sys.stdin.buffer
    while True:
        line = stdin_buf.readline()
        if not line:
            return 0
        try:
            request = json.loads(line.decode("utf-8"))
        except Exception as exc:
            _emit_error(None, "invalid_request", f"{type(exc).__name__}: {exc}")
            continue

        request_id = request.get("id")
        cmd = request.get("cmd")
        args = request.get("args") if isinstance(request.get("args"), dict) else {}

        try:
            result = _dispatch(cmd, args)
            _emit_success(request_id, result)
        except PermissionError as exc:
            _emit_error(
                request_id,
                "sandbox_access_denied",
                f"AppContainer blocked access: {exc}",
            )
        except FileNotFoundError as exc:
            _emit_error(request_id, "not_found", str(exc))
        except IsADirectoryError as exc:
            _emit_error(request_id, "is_a_directory", str(exc))
        except ValueError as exc:
            _emit_error(request_id, "invalid_arguments", str(exc))
        except subprocess.TimeoutExpired as exc:
            _emit_error(request_id, "timeout", f"command timed out after {exc.timeout}s")
        except Exception as exc:
            _emit_error(
                request_id,
                "worker_unhandled",
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}",
            )


def _dispatch(cmd: Any, args: dict[str, Any]) -> dict[str, Any]:
    if cmd == "terminal.run":
        return _run_terminal(args)
    if cmd in ("read_file", "write_file", "patch", "search_files"):
        return _run_file_tool(str(cmd), args)
    if cmd == "ping":
        return {"pong": True, "pid": os.getpid()}
    if cmd == "probe":
        # 발표 데모용. 워크스페이스 밖 파일에 접근을 시도해 OS 차단을 직접 확인한다.
        return _probe(args)
    raise ValueError(f"unsupported cmd: {cmd}")


def _run_file_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    file_tools = _load_file_tools()
    handler = {
        "read_file": file_tools.read_file,
        "write_file": file_tools.write_file,
        "patch": file_tools.patch,
        "search_files": file_tools.search_files,
    }[name]
    return handler(args)


def _run_terminal(args: dict[str, Any]) -> dict[str, Any]:
    argv = list(args.get("argv") or []) or None
    command = args.get("command")
    workspace_root = Path(str(args.get("workspace_root") or os.getcwd())).resolve()

    blocked = _blocked_terminal_command(command=command, argv=argv)
    if blocked is not None:
        return blocked

    cwd = _resolve_cwd(args.get("cwd"), workspace_root=workspace_root)
    timeout_seconds = float(args.get("timeout_seconds") or 15.0)

    # 윈도우 cmd 출력은 시스템 ANSI 코드페이지 (한국어 환경 = cp949). utf-8 강제 디코드하면
    # UnicodeDecodeError. errors='replace' 로 깨진 바이트도 통과시켜 LLM 에 결과는 전달되게.
    # CREATE_NO_WINDOW 로 cmd 콘솔창 깜빡임 제거.
    CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
    if argv:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        executed = list(argv)
    elif command:
        completed = subprocess.run(
            str(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=True,
            creationflags=CREATE_NO_WINDOW,
        )
        executed = [str(command)]
    else:
        raise ValueError("command or argv is required")

    stdout, stdout_truncated = _truncate_stream("stdout", completed.stdout or "")
    stderr, stderr_truncated = _truncate_stream("stderr", completed.stderr or "")
    return {
        "command": executed,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def _resolve_cwd(value: Any, *, workspace_root: Path) -> Path:
    raw = str(value or "").strip()
    candidate = Path(raw).expanduser() if raw else workspace_root
    resolved = candidate if candidate.is_absolute() else (workspace_root / candidate)
    resolved = resolved.resolve(strict=False)
    if not _is_relative_to(resolved, workspace_root):
        return workspace_root
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _blocked_terminal_command(*, command: Any, argv: list[Any] | None) -> dict[str, Any] | None:
    text = _command_text(command=command, argv=argv)
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if not any(re.search(pattern, normalized) for pattern in BLOCKED_PATTERNS):
        return None
    executed = list(argv) if argv else [str(command)]
    return {
        "ok": False,
        "error": {
            "code": "blocked_command",
            "message": "dangerous terminal command blocked before execution",
            "tool_name": "terminal.run",
        },
        "command": executed,
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }


def _command_text(*, command: Any, argv: list[Any] | None) -> str:
    if argv:
        return " ".join(str(item) for item in argv)
    if isinstance(command, str):
        return command
    return ""


def _truncate_stream(field_name: str, value: str) -> tuple[str, bool]:
    if len(value) <= MAX_TERMINAL_STREAM_CHARS:
        return value, False
    marker = f"\n[truncated: {field_name} exceeded {MAX_TERMINAL_STREAM_CHARS} chars]\n"
    keep = max(0, MAX_TERMINAL_STREAM_CHARS - len(marker))
    return value[:keep] + marker, True


def _probe(args: dict[str, Any]) -> dict[str, Any]:
    """샌드박스 동작 직접 확인. 발표 시연용."""

    target = str(args.get("target") or r"C:\Windows\System32\drivers\etc\hosts")
    result: dict[str, Any] = {"target": target, "denied": False, "error": None, "bytes": 0}
    try:
        with open(target, "rb") as handle:
            data = handle.read(64)
        result["bytes"] = len(data)
    except PermissionError as exc:
        result["denied"] = True
        result["error"] = f"PermissionError: {exc}"
    except OSError as exc:
        # AppContainer 가 파일 자체 보기는 허용하고 open 만 막을 수도 있다. 같은 의미로 처리.
        result["denied"] = True
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _emit_success(request_id: Any, result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({"id": request_id, "ok": True, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _emit_error(request_id: Any, code: str, message: str) -> None:
    sys.stdout.write(
        json.dumps(
            {"id": request_id, "ok": False, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        )
        + "\n"
    )
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
