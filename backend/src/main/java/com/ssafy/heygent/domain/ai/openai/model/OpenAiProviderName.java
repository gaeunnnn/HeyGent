package com.ssafy.heygent.domain.ai.openai.model;

import java.util.Arrays;
import java.util.List;
import java.util.stream.Stream;

import org.springframework.util.StringUtils;

import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;

import lombok.Getter;

@Getter
public enum OpenAiProviderName {

    OPENAI_API_KEY(
        "openai_api_key",
        "api_key",
        "openai",
        "OpenAI API Key",
        "일반 GPT 모델을 사용합니다.",
        "api_key",
        List.of("openai_user_api_key"),
        List.of("gpt-5.4", "gpt-5.4-mini", "gpt-5.2")
    ),
    GEMINI_API_KEY(
        "gemini_api_key",
        "api_key",
        "gemini",
        "Gemini API Key",
        "Gemini 모델을 사용합니다.",
        "api_key",
        List.of(),
        List.of("gemini-2.5-pro", "gemini-2.5-flash")
    ),
    CLAUDE_API_KEY(
        "claude_api_key",
        "api_key",
        "claude",
        "Claude API Key",
        "Claude 모델을 사용합니다.",
        "api_key",
        List.of("anthropic_api_key"),
        List.of("claude-sonnet-4.5", "claude-haiku-4.5")
    ),
    OPENAI_CODEX_OAUTH(
        "openai_codex_oauth",
        "oauth",
        "openai_codex",
        "Codex 연결",
        "Codex 전용 모델을 사용합니다.",
        "device_auth",
        List.of("codex_oauth", "openai-codex"),
        List.of("gpt-5.3-codex", "gpt-5.2-codex", "gpt-5-codex-mini")
    ),
    OPENAI_DEV_FALLBACK(
        "openai_dev_fallback",
        "api_key",
        "openai",
        "개발용 OpenAI",
        "개발 환경에서 서버 API Key를 사용합니다.",
        "dev_fallback",
        List.of(),
        List.of("gpt-5.4", "gpt-5.4-mini", "gpt-5.2")
    );

    private final String value;
    private final String authType;
    private final String providerType;
    private final String displayName;
    private final String description;
    private final String connectType;
    private final List<String> aliases;
    private final List<String> defaultModels;

    OpenAiProviderName(
        String value,
        String authType,
        String providerType,
        String displayName,
        String description,
        String connectType,
        List<String> aliases,
        List<String> defaultModels
    ) {
        this.value = value;
        this.authType = authType;
        this.providerType = providerType;
        this.displayName = displayName;
        this.description = description;
        this.connectType = connectType;
        this.aliases = aliases;
        this.defaultModels = defaultModels;
    }

    public static OpenAiProviderName from(String value) {
        if (!StringUtils.hasText(value)) {
            return OPENAI_DEV_FALLBACK;
        }

        String normalizedValue = value.trim();
        return Arrays.stream(values())
            .filter(provider -> provider.value.equals(normalizedValue)
                || provider.aliases.contains(normalizedValue))
            .findFirst()
            .orElseThrow(() -> new CustomException(ErrorCode.OPENAI_PROVIDER_NOT_SUPPORTED));
    }

    public boolean isApiKeyProvider() {
        return "api_key".equals(authType);
    }

    public boolean isUserManagedApiKeyProvider() {
        return this == OPENAI_API_KEY || this == GEMINI_API_KEY || this == CLAUDE_API_KEY;
    }

    public boolean isCodexOAuthProvider() {
        return this == OPENAI_CODEX_OAUTH;
    }

    public boolean supportsUsageQuery() {
        return this == OPENAI_API_KEY || this == OPENAI_DEV_FALLBACK;
    }

    public List<String> lookupValues() {
        return Stream.concat(Stream.of(value), aliases.stream())
            .toList();
    }
}
