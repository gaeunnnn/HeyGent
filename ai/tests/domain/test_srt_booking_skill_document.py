from pathlib import Path


def test_srt_booking_skill_uses_k_agent_secrets_document_for_credentials():
    content = Path("app/skills/k-skills/srt-booking/SKILL.md").read_text(encoding="utf-8")

    assert "`skill.run_script`" in content
    assert "scripts/srt_booking.py" in content
    assert "required_secret_keys" in content
    assert "SRT 회원번호, 이메일, 휴대전화번호 중 하나" in content
    assert "하이픈 포함 권장" in content
    assert "K-agent 설정의 `SECRETS.md`" in content
    assert "## srt-booking (암호화 저장 완료)" in content
    assert "채팅창에 비밀번호를 직접 입력하라고 요구하지 않는다" in content
    assert "~/.config/k-skill/secrets.env" not in content
    assert "Credential resolution order" not in content


def test_srt_booking_skill_bundles_runtime_script():
    script = Path("app/skills/k-skills/srt-booking/scripts/srt_booking.py")

    assert script.exists()
    assert "import SRT" in script.read_text(encoding="utf-8")
