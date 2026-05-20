import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'
import { Loader2 } from 'lucide-react'
import { kakaoLogin } from '@/apis/auth'
import { getMyInfo } from '@/apis/users'
import { useAuthStore } from '@/store/useAuthStore'

export function KakaoCallbackPage() {
  const navigate = useNavigate()
  const { setTokens, setUserInfo } = useAuthStore()
  const called = useRef(false)

  useEffect(() => {
    if (called.current) return
    called.current = true

    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const error = params.get('error')

    if (error || !code) {
      navigate('/login', { replace: true })
      return
    }

    kakaoLogin(code)
      .then(async (res) => {
        setTokens(res.data.accessToken, res.data.refreshToken)
        // 토큰 발급 직후 사용자 정보 조회
        try {
          const userRes = await getMyInfo()
          setUserInfo(userRes.data)
        } catch {
          // 사용자 정보 조회 실패해도 로그인 자체는 진행
        }
        navigate('/agent-status', { replace: true })
      })
      .catch(() => {
        navigate('/login', { replace: true })
      })
  }, [navigate, setTokens, setUserInfo])

  return (
    <div className="bg-background flex h-screen w-full flex-col items-center justify-center gap-4">
      <Loader2 className="text-primary h-8 w-8 animate-spin" />
      <p className="text-muted-foreground text-sm">카카오 로그인 중...</p>
    </div>
  )
}
