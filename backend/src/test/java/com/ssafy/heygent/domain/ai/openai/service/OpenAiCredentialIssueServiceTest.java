package com.ssafy.heygent.domain.ai.openai.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.lang.reflect.Field;
import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.env.Environment;

import com.ssafy.heygent.domain.ai.dto.request.OpenAiCredentialIssueRequest;
import com.ssafy.heygent.domain.ai.dto.response.OpenAiCredentialIssueResponse;
import com.ssafy.heygent.domain.ai.openai.config.OpenAiProperties;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;

@ExtendWith(MockitoExtension.class)
class OpenAiCredentialIssueServiceTest {

    @Mock
    private Environment environment;

    @Mock
    private OpenAiApiKeyService openAiApiKeyService;

    @Mock
    private OpenAiCodexOAuthService openAiCodexOAuthService;

    private OpenAiCredentialIssueService openAiCredentialIssueService;

    @BeforeEach
    void setUp() {
        OpenAiProperties properties = new OpenAiProperties();
        properties.setApiKey("dev-key");
        properties.setAllowedModels(List.of("gpt-5.4", "gpt-5.4-mini", "gpt-5.2"));
        OpenAiRuntimePolicyService runtimePolicyService = new OpenAiRuntimePolicyService(properties, environment);
        openAiCredentialIssueService = new OpenAiCredentialIssueService(
            properties,
            runtimePolicyService,
            openAiApiKeyService,
            openAiCodexOAuthService
        );
    }

    @Test
    void issueReturnsUserApiKeyCredential() throws Exception {
        OpenAiCredentialIssueRequest request = request("openai_api_key");
        when(openAiApiKeyService.resolveApiKey(eq(1L), any())).thenReturn("user-key");

        OpenAiCredentialIssueResponse response = openAiCredentialIssueService.issue(request);

        assertThat(response.getProviderName()).isEqualTo("openai_api_key");
        assertThat(response.getCredentialType()).isEqualTo("api_key");
        assertThat(response.getCredential()).isEqualTo("user-key");
        verify(openAiApiKeyService).resolveApiKey(eq(1L), any());
    }

    @Test
    void issueAllowsGpt52ForUserApiKeyCredential() throws Exception {
        OpenAiCredentialIssueRequest request = request("openai_api_key", "gpt-5.2");
        when(openAiApiKeyService.resolveApiKey(eq(1L), any())).thenReturn("user-key");

        OpenAiCredentialIssueResponse response = openAiCredentialIssueService.issue(request);

        assertThat(response.getProviderName()).isEqualTo("openai_api_key");
        assertThat(response.getModel()).isEqualTo("gpt-5.2");
        verify(openAiApiKeyService).resolveApiKey(eq(1L), any());
    }

    @Test
    void issueReturnsGeminiApiKeyCredential() throws Exception {
        OpenAiCredentialIssueRequest request = request("gemini_api_key", "gemini-2.5-pro");
        when(openAiApiKeyService.resolveApiKey(eq(1L), any())).thenReturn("gemini-key");

        OpenAiCredentialIssueResponse response = openAiCredentialIssueService.issue(request);

        assertThat(response.getProviderName()).isEqualTo("gemini_api_key");
        assertThat(response.getAuthType()).isEqualTo("api_key");
        assertThat(response.getCredentialType()).isEqualTo("api_key");
        assertThat(response.getCredential()).isEqualTo("gemini-key");
    }

    @Test
    void issueDoesNotUseDevFallbackWhenOpenAiUserApiKeyIsMissingInLocalProfile() throws Exception {
        OpenAiCredentialIssueRequest request = request("openai_api_key");
        when(openAiApiKeyService.resolveApiKey(eq(1L), any()))
            .thenThrow(new CustomException(ErrorCode.OPENAI_PROVIDER_NOT_CONNECTED));

        assertThatThrownBy(() -> openAiCredentialIssueService.issue(request))
            .isInstanceOf(CustomException.class)
            .hasFieldOrPropertyWithValue("errorCode", ErrorCode.OPENAI_PROVIDER_NOT_CONNECTED);
        verify(openAiApiKeyService).resolveApiKey(eq(1L), any());
    }

    @Test
    void issueUsesDevFallbackOnlyWhenExplicitProviderIsRequested() throws Exception {
        OpenAiCredentialIssueRequest request = request("openai_dev_fallback");
        when(environment.matchesProfiles("dev")).thenReturn(false);
        when(environment.matchesProfiles("local")).thenReturn(true);

        OpenAiCredentialIssueResponse response = openAiCredentialIssueService.issue(request);

        assertThat(response.getProviderName()).isEqualTo("openai_dev_fallback");
        assertThat(response.getCredentialType()).isEqualTo("api_key");
        assertThat(response.getCredential()).isEqualTo("dev-key");
        verify(openAiApiKeyService, never()).resolveApiKey(any(), any());
    }

    @Test
    void issueRejectsCodexOauthCredential() throws Exception {
        OpenAiCredentialIssueRequest request = request("openai_codex_oauth", "gpt-5.3-codex");

        assertThatThrownBy(() -> openAiCredentialIssueService.issue(request))
            .isInstanceOf(CustomException.class);
    }

    private OpenAiCredentialIssueRequest request(String providerName) throws Exception {
        return request(providerName, "gpt-5.4");
    }

    private OpenAiCredentialIssueRequest request(String providerName, String model) throws Exception {
        OpenAiCredentialIssueRequest request = new OpenAiCredentialIssueRequest();
        set(request, "userId", 1L);
        set(request, "providerName", providerName);
        set(request, "model", model);
        return request;
    }

    private void set(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
