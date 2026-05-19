package com.ssafy.heygent.domain.ai.openai.client;

import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import com.ssafy.heygent.global.config.security.AiInternalProperties;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
@RequiredArgsConstructor
public class OpenAiCredentialCacheClient {

    private final AiInternalProperties aiInternalProperties;
    private final RestTemplate restTemplate = new RestTemplate();

    public void invalidate(Long userId, String providerName) {
        String url = aiInternalProperties.getCredentialCacheInvalidateUrl();
        String token = aiInternalProperties.getToken();
        if (!StringUtils.hasText(url) || !StringUtils.hasText(token)) {
            log.debug("AI credential cache 무효화 생략: 내부 URL 또는 token이 설정되지 않았습니다.");
            return;
        }

        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(token);
        headers.setContentType(MediaType.APPLICATION_JSON);

        try {
            restTemplate.postForEntity(
                url,
                new HttpEntity<>(new InvalidateRequest(userId, providerName), headers),
                Void.class
            );
        } catch (RestClientException exception) {
            // credential cache 무효화는 저장된 key의 "즉시 반영"을 위한 보조 동작이다.
            // AI 서버가 일시적으로 내려가 있어도 DB 저장 자체를 실패시키면 사용자가 key를
            // 다시 입력해야 하므로, 저장 요청은 성공시키고 다음 요청/재시작/TTL 만료에 맡긴다.
            log.warn("AI credential cache 무효화 실패: userId={}, providerName={}, reason={}",
                userId,
                providerName,
                exception.getMessage()
            );
        }
    }

    private record InvalidateRequest(Long userId, String providerName) {
    }
}
