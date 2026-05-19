package com.ssafy.heygent.domain.gmail.service;

import java.nio.charset.StandardCharsets;
import java.time.Duration;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.web.client.RestTemplate;

final class GmailUtf8RestTemplateFactory {

    private GmailUtf8RestTemplateFactory() {
    }

    static RestTemplate create() {
        // Composio proxy 는 format=full 본문 풀로딩 시 응답이 수 초 이상 걸린다.
        // 기본(무제한) 으로 두면 AI 측 timeout(30s) 도달 시 Broken pipe 가 발생하므로
        // 25 초 read timeout 으로 명시해 backend 가 먼저 자르도록 한다.
        RestTemplate restTemplate = new RestTemplateBuilder()
            .setConnectTimeout(Duration.ofSeconds(5))
            .setReadTimeout(Duration.ofSeconds(25))
            .build();
        restTemplate.getMessageConverters().removeIf(StringHttpMessageConverter.class::isInstance);
        restTemplate.getMessageConverters().add(1, new StringHttpMessageConverter(StandardCharsets.UTF_8));
        return restTemplate;
    }
}
