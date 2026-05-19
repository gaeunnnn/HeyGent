# Local Bridge 구조

## 개요

브릿지는 사용자 PC에서 실행되는 Python 프로그램입니다. 클라우드 AI 서버가 사용자 PC 자원에 직접 접근할 수 없기 때문에, 브릿지가 중간에서 제한된 로컬 작업을 대신 실행합니다.

기준 위치: `bridge/`

## 실행 흐름

```text
[Web] 페어링 코드 발급
   |
   v
[Bridge GUI] 코드 입력
   |
   v
[Backend] 사용자-기기 연결 저장
   |
   v
[AI Server] 브릿지 WebSocket으로 도구 실행 요청
   |
   v
[User PC Bridge] terminal/file 도구 실행
```

## 주요 파일

| 파일 | 역할 |
| --- | --- |
| `main.py` | 콘솔 모드 실행 진입점 |
| `tray.py` | GUI/트레이 모드 실행 진입점 |
| `pairing.py` | 페어링 코드와 토큰 저장 |
| `executor.py` | terminal/file 도구 실행 |
| `_file_tools.py` | 파일 읽기/쓰기/patch/search 구현 |
| `storage.py` | 로컬 브릿지 설정 저장 |
| `config.py` | 환경 변수 로딩 |

## 지원 도구

- `terminal.run`: 로컬 셸 명령 실행
- `read_file`: 파일 읽기
- `write_file`: 파일 쓰기
- `patch`: 파일 일부 수정
- `search_files`: 파일 검색

## 보안 기준

- 브릿지는 `BRIDGE_WORKSPACE_ROOT` 안에서만 파일 작업을 수행합니다.
- 페어링 토큰은 사용자 PC의 로컬 저장소에 보관됩니다.
- 한 사용자 계정에 여러 브릿지를 무제한 붙이는 구조가 아니라, 사용자별 기기 연결을 backend가 관리합니다.
- 위험한 파일 작업이나 의도하지 않은 경로 접근은 브릿지 실행 계층에서 제한해야 합니다.
