package com.ssafy.heygent.global.config.security;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Component
@ConfigurationProperties(prefix = "ai.internal")
public class AiInternalProperties {

    private String token;
    /**
     * AI 서버의 "현재 WebSocket 으로 붙어있는 브릿지 user_id 목록" 조회 URL.
     * 컨테이너 안에서 통신하므로 service 이름 기반. 환경별 .env 로 override 가능.
     */
    private String onlineUsersUrl;

    /**
     * provider API key 저장/삭제 후 AI 런타임의 credential cache를 지우는 내부 URL.
     * DB에는 새 key가 저장됐는데 AI 서버가 이전 key를 TTL 동안 계속 쓰는 상황을 막기 위해 사용한다.
     */
    private String credentialCacheInvalidateUrl;
}
