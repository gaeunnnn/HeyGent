"""HeyGent 브릿지 AppContainer 샌드박스.

설계 요약 (자세한 배경은 docs/security/bridge-sandbox.md 참고):
  - 브릿지 본체는 사용자 권한으로 실행되어 AI 서버 통신/페어링 토큰 관리만 담당한다.
  - AI 가 시키는 모든 도구 호출(터미널, 파일 IO, 검색)은 본 모듈이 띄우는 워커 자식
    프로세스 안에서 실행된다.
  - 워커는 Win32 AppContainer 안에서 돌고, 워크스페이스 폴더 ACL 에 명시적으로 허용한
    AppContainer SID 외에는 어떤 파일/네트워크/레지스트리에도 접근하지 못한다.
  - 워커가 죽거나 행 걸리면 본체가 죽이고 다시 띄운다. 토큰 저장소는 절대 닿지 않는다.

이 파일은 ctypes 로 직접 Win32 API 를 부른다 (pywin32 는 AppContainer 관련 API 를
충분히 노출하지 않아 ctypes 가 더 안정적). 호출 흐름:
  1) ensure_app_container_profile() → CreateAppContainerProfile / DeriveAppContainerSidFromName
  2) grant_app_container_to_path()  → icacls 로 워크스페이스 폴더에 SID 허용 ACL 추가
  3) launch_worker()                → CreateProcessW(... SECURITY_CAPABILITIES ...)

Windows 10 1709+ 부터 AppContainer 가 정상 동작한다. 그 이하 환경에서는
샌드박스 없이 도는 폴백을 제공하되, GUI 에서 명시적으로 알려준다.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO


logger = logging.getLogger("bridge.sandbox")


# 우리 AppContainer 프로필 이름. 단일 이름이라 같은 PC 에 여러 사용자가 써도 충돌 안 난다 (사용자별 격리됨).
APP_CONTAINER_PROFILE_NAME = "com.heygent.bridge.sandbox"
APP_CONTAINER_DISPLAY_NAME = "HeyGent Bridge Sandbox"
APP_CONTAINER_DESCRIPTION = (
    "AppContainer profile that isolates HeyGent bridge worker. "
    "Restricts worker to workspace folder only; no network, no registry, no other processes."
)

# 워커 응답 대기 기본 타임아웃. 모델이 시키는 명령이 길 수 있어 60초까지 둠.
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0

# WIN32 상수.
ERROR_ALREADY_EXISTS = 183
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NO_WINDOW = 0x08000000
HANDLE_FLAG_INHERIT = 0x00000001
STARTF_USESTDHANDLES = 0x00000100


# --- Win32 구조체/시그니처 정의 -------------------------------------------------


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SidAndAttributes)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _StartupInfoExW(ctypes.Structure):
    class _Inner(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    _fields_ = [
        ("StartupInfo", _Inner),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _is_windows() -> bool:
    return os.name == "nt"


def _supports_app_container() -> bool:
    if not _is_windows():
        return False
    try:
        release = platform.release()
        if release.isdigit() and int(release) >= 10:
            return True
        # Server 2016+ also fine.
        return "Server" in release and any(c.isdigit() for c in release)
    except Exception:
        return False


# --- AppContainer 프로필 관리 ---------------------------------------------------


def ensure_app_container_profile() -> bytes:
    """프로필이 없으면 만들고 SID 를 돌려준다. 이미 있으면 그 SID 를 돌려준다.

    SID 는 binary 형태 (PSID). FreeSid 는 호출하지 않는다 — 동일 프로세스 수명 동안 재사용한다.
    """

    if not _supports_app_container():
        raise RuntimeError("AppContainer requires Windows 10 1709+")

    userenv = ctypes.windll.userenv

    # 1) DeriveAppContainerSidFromAppContainerName 으로 기존 프로필 SID 조회 시도.
    sid_ptr = ctypes.c_void_p()
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    derive.restype = wintypes.LONG
    hr = derive(APP_CONTAINER_PROFILE_NAME, ctypes.byref(sid_ptr))
    if hr == 0 and sid_ptr.value:
        return _sid_to_bytes(sid_ptr.value)

    # 2) 없으면 CreateAppContainerProfile 로 새로 만든다. capabilities 는 모두 비워둔다
    #    (인터넷/레지스트리/사용자파일 등 모든 능력 거부). 워크스페이스만 ACL 로 명시 허용한다.
    create = userenv.CreateAppContainerProfile
    create.argtypes = [
        wintypes.LPCWSTR,  # pszAppContainerName
        wintypes.LPCWSTR,  # pszDisplayName
        wintypes.LPCWSTR,  # pszDescription
        ctypes.c_void_p,   # pCapabilities (PSID_AND_ATTRIBUTES)
        wintypes.DWORD,    # dwCapabilityCount
        ctypes.POINTER(ctypes.c_void_p),  # ppSidAppContainerSid
    ]
    create.restype = wintypes.LONG
    new_sid_ptr = ctypes.c_void_p()
    hr = create(
        APP_CONTAINER_PROFILE_NAME,
        APP_CONTAINER_DISPLAY_NAME,
        APP_CONTAINER_DESCRIPTION,
        None,
        0,
        ctypes.byref(new_sid_ptr),
    )
    if hr == 0 and new_sid_ptr.value:
        return _sid_to_bytes(new_sid_ptr.value)

    # 0x800700b7 = HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS). 다른 프로세스가 동시에 만들었을 때
    # 다시 한 번 Derive 로 회수한다.
    if hr in (-2147024713, 0x800700B7):
        hr2 = derive(APP_CONTAINER_PROFILE_NAME, ctypes.byref(sid_ptr))
        if hr2 == 0 and sid_ptr.value:
            return _sid_to_bytes(sid_ptr.value)

    raise OSError(f"CreateAppContainerProfile failed with HRESULT=0x{hr & 0xFFFFFFFF:08X}")


def _sid_to_bytes(sid_ptr: int) -> bytes:
    """PSID 포인터 → 우리가 다루기 편한 bytes 표현. ConvertSidToStringSid 결과 'S-1-15-2-...' 도 함께 보관용으로 로깅."""

    advapi32 = ctypes.windll.advapi32
    get_length = advapi32.GetLengthSid
    get_length.argtypes = [ctypes.c_void_p]
    get_length.restype = wintypes.DWORD
    length = get_length(sid_ptr)
    raw = ctypes.string_at(sid_ptr, length)

    # 디버깅용 SID 문자열도 한 번 찍어두면 발표/지원 때 편하다.
    convert = advapi32.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert.restype = wintypes.BOOL
    str_ptr = wintypes.LPWSTR()
    if convert(sid_ptr, ctypes.byref(str_ptr)):
        try:
            logger.info("AppContainer SID: %s", str_ptr.value)
        finally:
            ctypes.windll.kernel32.LocalFree(str_ptr)
    return raw


def app_container_sid_string() -> str:
    """발표/UI 용으로 SID 문자열 표현을 조회한다."""

    sid_bytes = ensure_app_container_profile()
    # bytes → temporary PSID buffer
    buf = (ctypes.c_ubyte * len(sid_bytes)).from_buffer_copy(sid_bytes)
    advapi32 = ctypes.windll.advapi32
    convert = advapi32.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert.restype = wintypes.BOOL
    str_ptr = wintypes.LPWSTR()
    if not convert(ctypes.addressof(buf), ctypes.byref(str_ptr)):
        return ""
    try:
        return str_ptr.value or ""
    finally:
        ctypes.windll.kernel32.LocalFree(str_ptr)


# --- 워크스페이스 ACL ----------------------------------------------------------


# 동일 워크스페이스에 두 번 grant 하지 않도록 메모리 캐시. 프로세스 수명 동안 유지.
_acl_granted_paths: set[str] = set()


def grant_app_container_to_path(path: Path) -> None:
    """워크스페이스 폴더 ACL 에 우리 AppContainer 의 읽기/쓰기/실행 권한을 추가한다.

    추가로 부모 디렉터리 체인 모두에 traverse(X) 권한도 부여한다. AppContainer 자식이
    워크스페이스에 들어가려면 모든 상위 폴더에 traverse 권한이 있어야 한다.

    매 워커 spawn 마다 호출되지만, 이미 한 번 grant 한 경로는 메모리 캐시로 skip 한다.
    icacls 가 분 단위로 걸려서 매 호출마다 사용자 체감 응답성이 망가졌었음.
    """

    if not _is_windows():
        return

    cache_key = str(path)
    if cache_key in _acl_granted_paths:
        return

    sid_str = app_container_sid_string()
    if not sid_str:
        raise OSError("Failed to resolve AppContainer SID before granting ACL")

    # 워크스페이스 자체에 전체 권한 + 상속 부여. .exe 사본을 워크스페이스 안에 두기 때문에
    # 부모 폴더 traverse 권한을 따로 부여할 필요가 없다.
    # (이전 버전은 C:\Users\SSAFY 까지 거슬러 올라가며 24초+ 걸렸음.)
    _icacls_grant(str(path), f"*{sid_str}:(OI)(CI)(F)", recursive=True)

    _acl_granted_paths.add(cache_key)


def _icacls_grant(target: str, ace: str, *, recursive: bool) -> None:
    cmd = ["icacls", target, "/grant", ace, "/C"]
    if recursive:
        cmd.append("/T")
    logger.info("icacls %s grant %s", target, ace)
    # CREATE_NO_WINDOW 로 icacls 자식의 콘솔창 깜빡임 제거. GUI 모드 브릿지에서 ACL 부여마다
    # cmd 창이 깜빡이는 게 사용자에게 불안하게 보였음.
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        creationflags=CREATE_NO_WINDOW if _is_windows() else 0,
    )
    if completed.returncode != 0:
        logger.warning(
            "icacls grant on %s returned %s. stdout=%s stderr=%s",
            target,
            completed.returncode,
            completed.stdout[:300],
            completed.stderr[:300],
        )


# --- AppContainer 자식 프로세스 launcher ---------------------------------------


@dataclass
class WorkerHandle:
    """워커 프로세스 핸들. 표준입출력 파이프로 명령을 주고받는다."""

    process_handle: int
    thread_handle: int
    pid: int
    stdin: IO[bytes]
    stdout: IO[bytes]
    stderr_path: Path
    lock: threading.Lock
    sandboxed: bool
    workspace_root: Path

    def call(self, request: dict[str, Any], *, timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS) -> dict[str, Any]:
        """워커에 요청 한 줄을 보내고 응답 한 줄을 받는다.

        파이프는 단방향 stream 이므로 동시 호출이 끼면 응답이 섞인다. lock 으로 직렬화.
        """

        line = json.dumps(request, ensure_ascii=False) + "\n"
        with self.lock:
            self.stdin.write(line.encode("utf-8"))
            self.stdin.flush()
            response_line = _read_line_with_timeout(self.stdout, timeout_seconds=timeout)
        if not response_line:
            raise OSError("worker pipe closed before response")
        return json.loads(response_line.decode("utf-8", errors="replace"))

    @property
    def dead(self) -> bool:
        if not _is_windows():
            return False
        kernel32 = ctypes.windll.kernel32
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(self.process_handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value != 259  # STILL_ACTIVE

    def terminate(self) -> None:
        if not _is_windows():
            return
        kernel32 = ctypes.windll.kernel32
        try:
            kernel32.TerminateProcess(self.process_handle, 1)
        except Exception:
            pass
        for handle in (self.process_handle, self.thread_handle):
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
        try:
            self.stdin.close()
        except Exception:
            pass
        try:
            self.stdout.close()
        except Exception:
            pass


def _build_pipe_security_descriptor(sid_bytes: bytes | None) -> Any:
    """파이프 핸들에 AppContainer SID 의 GENERIC_ALL 권한을 허용하는 SD 를 만든다.

    포함자: 본 프로세스 토큰의 OWNER + AppContainer SID. AppContainer 안의 자식이 상속받은
    파이프 핸들로 ReadFile/WriteFile 호출할 때 ACL 체크가 통과되도록 한다.

    리턴: SECURITY_DESCRIPTOR self-relative buffer (ctypes c_char 배열). 호출자는 buffer 의
    수명을 spawn 끝까지 유지해야 한다.
    """

    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32

    if sid_bytes is None:
        # 비-격리 폴백: NULL SD 로 부모 토큰 ACL 만 적용한다.
        return None

    # SDDL 로 SID 두 개에 풀권한 부여. CO=Creator Owner, BA=Built-in Administrators,
    # 그리고 명시적 AppContainer SID. WD=Everyone 은 일부러 빼서 격리 의미 보존.
    sid_str = ""
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    sid_buffer = (ctypes.c_ubyte * len(sid_bytes)).from_buffer_copy(sid_bytes)
    str_ptr = wintypes.LPWSTR()
    if advapi32.ConvertSidToStringSidW(ctypes.addressof(sid_buffer), ctypes.byref(str_ptr)):
        try:
            sid_str = str_ptr.value or ""
        finally:
            kernel32.LocalFree(str_ptr)
    if not sid_str:
        return None

    # Owner/Group 은 비워서 CreatePipe 가 호출자 토큰의 기본값을 쓰게 한다 (Owner=현재 사용자).
    # ACL: 현재 사용자(OW=Owner Rights)/SYSTEM/AppContainer SID 풀권한.
    sddl = (
        "D:"
        "(A;;GA;;;OW)"
        "(A;;GA;;;SY)"
        "(A;;GA;;;BA)"
        f"(A;;GA;;;{sid_str})"
    )

    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

    sd_ptr = ctypes.c_void_p()
    sd_size = wintypes.DWORD(0)
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,  # SDDL_REVISION_1
        ctypes.byref(sd_ptr),
        ctypes.byref(sd_size),
    ):
        err = kernel32.GetLastError()
        logger.warning("ConvertStringSDtoSD failed err=0x%08X, falling back to NULL SD", err)
        return None
    # LocalFree 가 필요한 메모리지만, ctypes 가 회수하면 자식이 spawn 끝나기 전 죽을 수 있으니
    # 호출자 수명까지 그대로 들고 있는다. 본 프로세스가 종료될 때 OS 가 정리한다.
    buf = (ctypes.c_ubyte * sd_size.value).from_address(sd_ptr.value)
    return buf


def _build_env_block(extra: dict[str, str]) -> ctypes.Array:
    """CreateProcessW 의 lpEnvironment 용 UTF-16 환경블록을 만든다.

    형식: "KEY1=VAL1\0KEY2=VAL2\0...\0\0" (null-terminated strings + double-null terminator).
    부모 프로세스 환경을 그대로 상속하면서 extra dict 의 값만 덮어쓴다.
    """

    merged: dict[str, str] = dict(os.environ)
    merged.update(extra)
    parts: list[str] = [f"{key}={value}" for key, value in merged.items()]
    block_str = "\x00".join(parts) + "\x00\x00"
    return ctypes.create_unicode_buffer(block_str)


def _read_line_with_timeout(stream: IO[bytes], *, timeout_seconds: float) -> bytes:
    """stdout 파이프에서 한 줄을 timeout 안에 읽는다. 블로킹 read 라 별도 스레드 + Event 로 처리."""

    result: dict[str, bytes | None] = {"line": None}
    completed = threading.Event()

    def _reader() -> None:
        try:
            result["line"] = stream.readline()
        finally:
            completed.set()

    thread = threading.Thread(target=_reader, name="bridge-worker-read", daemon=True)
    thread.start()
    if not completed.wait(timeout=timeout_seconds):
        raise TimeoutError(f"worker did not respond within {timeout_seconds:.1f}s")
    return result["line"] or b""


def launch_worker(*, workspace_root: Path, worker_argv: list[str]) -> WorkerHandle:
    """AppContainer 안에서 워커 자식 프로세스를 띄우고 stdin/stdout 파이프를 연다.

    AppContainer 자체 생성/ACL 부여가 실패하면 (예: 권한 부족, 구버전 OS) 비-격리 폴백으로
    동작한다. 그래도 워커 분리는 유지되므로 토큰 저장소는 여전히 보호된다.
    """

    sandboxed = False
    sid_bytes: bytes | None = None
    if _supports_app_container():
        try:
            sid_bytes = ensure_app_container_profile()
            # 워크스페이스 (사용자 작업 폴더) + sandbox 런타임 폴더 (워커 .exe 사본 위치) 둘 다
            # AppContainer SID 가 접근 가능해야 함. worker.exe 가 후자에 있어서 spawn 시 필요.
            grant_app_container_to_path(workspace_root)
            worker_exe_path = Path(worker_argv[0])
            if worker_exe_path.parent.exists():
                grant_app_container_to_path(worker_exe_path.parent)
            sandboxed = True
        except Exception as exc:
            logger.exception("AppContainer 준비 실패, 폴백 모드로 워커를 띄움: %s", exc)

    if sandboxed:
        try:
            return _spawn_process(
                argv=worker_argv,
                cwd=workspace_root,
                sid_bytes=sid_bytes,
                workspace_root=workspace_root,
            )
        except OSError as exc:
            # AppContainer + CreateProcess 조합이 실패하면 (예: .exe 의존 폴더 traverse 누락 등
            # OS/환경 의존 이슈) 비-격리 모드로 워커는 띄운다. 토큰 저장소와 워커는 여전히 별도
            # 프로세스라 권한 최소화의 절반은 유지된다.
            logger.warning(
                "AppContainer spawn 실패 (%s). 비-격리 폴백으로 워커를 띄운다.", exc
            )

    return _spawn_process(
        argv=worker_argv,
        cwd=workspace_root,
        sid_bytes=None,
        workspace_root=workspace_root,
    )


def _spawn_process(
    *,
    argv: list[str],
    cwd: Path,
    sid_bytes: bytes | None,
    workspace_root: Path,
) -> WorkerHandle:
    if not _is_windows():
        raise RuntimeError("worker spawn requires Windows")

    kernel32 = ctypes.windll.kernel32

    # 파이프 생성. AppContainer 자식이 상속받은 핸들을 사용하려면 핸들 자체 ACL 에 SID 허용이
    # 들어가야 한다. 그래서 CreatePipe 의 SA 에 AppContainer SID 를 포함하는 보안 디스크립터를 건다.
    sa_inheritable = _SecurityAttributes()
    sa_inheritable.nLength = ctypes.sizeof(_SecurityAttributes)
    sa_inheritable.bInheritHandle = True
    sd_buffer = _build_pipe_security_descriptor(sid_bytes)
    sa_inheritable.lpSecurityDescriptor = (
        ctypes.cast(sd_buffer, ctypes.c_void_p).value if sd_buffer is not None else None
    )

    stdin_read = wintypes.HANDLE()
    stdin_write = wintypes.HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(stdin_read), ctypes.byref(stdin_write), ctypes.byref(sa_inheritable), 0):
        raise OSError("CreatePipe(stdin) failed")
    # 부모 쓰기 핸들은 상속되면 안 됨.
    kernel32.SetHandleInformation(stdin_write, HANDLE_FLAG_INHERIT, 0)

    stdout_read = wintypes.HANDLE()
    stdout_write = wintypes.HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(stdout_read), ctypes.byref(stdout_write), ctypes.byref(sa_inheritable), 0):
        raise OSError("CreatePipe(stdout) failed")
    kernel32.SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0)

    # stderr 는 sandbox 런타임 폴더 (워크스페이스 밖) 의 파일에 쓰게 한다. 사용자 워크스페이스
    # listing 에 우리 로그가 노출되지 않도록.
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    stderr_path = Path(base) / "HeyGent" / "sandbox" / "worker.stderr.log"
    try:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_file = open(stderr_path, "ab", buffering=0)  # noqa: SIM115 - 자식 수명 동안 보유
    except Exception:
        stderr_file = None
    # 파일 핸들 → win HANDLE (표준 msvcrt 모듈 사용)
    if stderr_file is not None:
        import msvcrt as _msvcrt
        stderr_handle_value = _msvcrt.get_osfhandle(stderr_file.fileno())
        stderr_handle = wintypes.HANDLE(stderr_handle_value)
        kernel32.SetHandleInformation(stderr_handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)
    else:
        stderr_handle = stdout_write  # 폴백: stderr 도 stdout 으로

    # AppContainer 속성 리스트.
    attr_list_size = ctypes.c_size_t(0)
    InitializeProcThreadAttributeList = kernel32.InitializeProcThreadAttributeList
    InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    InitializeProcThreadAttributeList.restype = wintypes.BOOL

    InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_list_size))
    attr_buffer = (ctypes.c_ubyte * attr_list_size.value)()
    if not InitializeProcThreadAttributeList(attr_buffer, 1, 0, ctypes.byref(attr_list_size)):
        raise OSError("InitializeProcThreadAttributeList failed")

    sec_capabilities = _SecurityCapabilities()
    sid_buffer = None
    capability_buffer = None  # 비어있어도 명시적 buffer 가 필요한 케이스 대비
    if sid_bytes is not None:
        sid_buffer = (ctypes.c_ubyte * len(sid_bytes)).from_buffer_copy(sid_bytes)
        # 빈 capability 배열을 명시적으로 만든다. NULL pointer 를 거부하는 윈도우 빌드 대비.
        capability_buffer = (_SidAndAttributes * 0)()
        sec_capabilities.AppContainerSid = ctypes.cast(sid_buffer, ctypes.c_void_p)
        sec_capabilities.Capabilities = ctypes.cast(capability_buffer, ctypes.POINTER(_SidAndAttributes))
        sec_capabilities.CapabilityCount = 0
        sec_capabilities.Reserved = 0

        UpdateProcThreadAttribute = kernel32.UpdateProcThreadAttribute
        UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        UpdateProcThreadAttribute.restype = wintypes.BOOL
        if not UpdateProcThreadAttribute(
            attr_buffer,
            0,
            ctypes.c_void_p(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
            ctypes.byref(sec_capabilities),
            ctypes.sizeof(sec_capabilities),
            None,
            None,
        ):
            raise OSError("UpdateProcThreadAttribute(SECURITY_CAPABILITIES) failed")

    startup = _StartupInfoExW()
    startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoExW)
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = stdin_read.value
    startup.StartupInfo.hStdOutput = stdout_write.value
    startup.StartupInfo.hStdError = stderr_handle.value if isinstance(stderr_handle, wintypes.HANDLE) else stderr_handle
    # ctypes 의 c_void_p 필드에는 int 가 아닌 c_void_p 인스턴스를 넣어야 64-bit 환경에서 안전하다.
    startup.lpAttributeList = ctypes.addressof(attr_buffer)

    process_info = _ProcessInformation()

    # AppContainer 분기에서는 lpApplicationName 을 지정하면 ERROR_FILE_NOT_FOUND 가 나는 케이스가
    # 보고됐다. 그래서 명시하지 않고, lpCommandLine 의 첫 토큰만으로 윈도우가 .exe 를 찾게 한다.
    # 비-AppContainer 분기에서는 둘 다 OK 라 동일하게 처리.
    app_name = None
    cmdline = subprocess.list2cmdline(argv)
    cmdline_buf = ctypes.create_unicode_buffer(cmdline)

    flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW

    CreateProcessW = kernel32.CreateProcessW
    CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoExW),
        ctypes.POINTER(_ProcessInformation),
    ]
    CreateProcessW.restype = wintypes.BOOL

    # 환경변수로 워크스페이스 path 전달. AppContainer 자식이 cwd 진입 권한이 없으면 윈도우가
    # 자동으로 C:\ 로 fallback 시키는데, 그 경우 워커가 chdir 로 직접 워크스페이스 진입해야
    # cmd/PowerShell 자식들이 올바른 위치에서 돌아간다.
    env_block = _build_env_block({"HEYGENT_BRIDGE_WORKSPACE": str(cwd)})

    success = CreateProcessW(
        app_name,
        cmdline_buf,
        None,
        None,
        True,
        flags | 0x00000400,  # CREATE_UNICODE_ENVIRONMENT
        ctypes.cast(env_block, ctypes.c_void_p),
        str(cwd),
        ctypes.byref(startup),
        ctypes.byref(process_info),
    )
    if not success:
        err = kernel32.GetLastError()
        raise OSError(f"CreateProcessW failed with GetLastError=0x{err:08X}")

    # 부모는 자식 쪽 파이프 끝을 닫아야 EOF 가 전파된다.
    kernel32.CloseHandle(stdin_read)
    kernel32.CloseHandle(stdout_write)

    # win HANDLE → python fd → file object. msvcrt._open_osfhandle 는 파이썬 표준
    # msvcrt 모듈을 쓴다 (cdll.msvcrt 는 Python 빌드와 ABI 가 어긋날 수 있음).
    # flags = _O_BINARY 로 명시. 0 으로 주면 "Bad handle" 로 fail 하는 윈도우 빌드가 있다.
    import msvcrt as _msvcrt
    _O_BINARY = 0x8000
    write_fd = _msvcrt.open_osfhandle(stdin_write.value, _O_BINARY)
    read_fd = _msvcrt.open_osfhandle(stdout_read.value, _O_BINARY)
    stdin_file = os.fdopen(write_fd, "wb", buffering=0)
    stdout_file = os.fdopen(read_fd, "rb", buffering=0)

    return WorkerHandle(
        process_handle=process_info.hProcess,
        thread_handle=process_info.hThread,
        pid=process_info.dwProcessId,
        stdin=stdin_file,
        stdout=stdout_file,
        stderr_path=stderr_path,
        lock=threading.Lock(),
        sandboxed=sid_bytes is not None,
        workspace_root=workspace_root,
    )


def status_summary() -> dict[str, Any]:
    """발표/UI 표시용 샌드박스 상태 요약."""

    if not _is_windows():
        return {"supported": False, "reason": "non-windows host", "sid": None}
    if not _supports_app_container():
        return {"supported": False, "reason": "windows version too old", "sid": None}
    try:
        sid_str = app_container_sid_string()
        return {"supported": True, "reason": None, "sid": sid_str}
    except Exception as exc:
        return {"supported": False, "reason": f"{type(exc).__name__}: {exc}", "sid": None}
