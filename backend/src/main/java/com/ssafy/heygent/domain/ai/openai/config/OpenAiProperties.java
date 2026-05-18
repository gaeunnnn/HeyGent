package com.ssafy.heygent.domain.ai.openai.config;

import java.util.ArrayList;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Component
@ConfigurationProperties(prefix = "openai")
public class OpenAiProperties {

    private String apiKey = "";
    private String restApiBaseUrl = "https://api.openai.com/v1";
    private String usageApiBaseUrl = "https://api.openai.com/v1";
    private String defaultModel = "gpt-5.4";
    private List<String> allowedModels = new ArrayList<>(List.of("gpt-5.4", "gpt-5.4-mini", "gpt-5.2"));
    private String embeddingModel = "text-embedding-3-small";
    private int timeoutSeconds = 60;
    private String credentialEncryptionKey = "";
    private CodexOAuth codexOAuth = new CodexOAuth();
    private CodexDeviceOAuth codexDeviceOAuth = new CodexDeviceOAuth();

    public boolean hasApiKey() {
        return StringUtils.hasText(apiKey);
    }

    public List<String> normalizedAllowedModels() {
        return allowedModels.stream()
            .filter(StringUtils::hasText)
            .map(String::trim)
            .toList();
    }

    public boolean hasCredentialEncryptionKey() {
        return StringUtils.hasText(credentialEncryptionKey);
    }

    @Getter
    @Setter
    public static class CodexOAuth {

        private String clientId = "app_EMoamEEZ73f0CkXaXp7hrann";
        private String tokenUrl = "https://auth.openai.com/oauth/token";
        private int refreshSkewSeconds = 300;
    }

    @Getter
    @Setter
    public static class CodexDeviceOAuth {

        private String command = "codex";
        private String workspaceRoot = "";
        private int startTimeoutSeconds = 30;
        private int authTimeoutSeconds = 900;
    }
}
