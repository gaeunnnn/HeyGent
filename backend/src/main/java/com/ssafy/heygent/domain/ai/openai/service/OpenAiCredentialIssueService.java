package com.ssafy.heygent.domain.ai.openai.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.ssafy.heygent.domain.ai.dto.request.OpenAiCredentialIssueRequest;
import com.ssafy.heygent.domain.ai.dto.response.OpenAiCredentialIssueResponse;
import com.ssafy.heygent.domain.ai.openai.config.OpenAiProperties;
import com.ssafy.heygent.domain.ai.openai.model.OpenAiProviderName;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class OpenAiCredentialIssueService {

    private final OpenAiProperties properties;
    private final OpenAiRuntimePolicyService runtimePolicyService;
    private final OpenAiApiKeyService openAiApiKeyService;
    private final OpenAiCodexOAuthService openAiCodexOAuthService;

    @Transactional
    public OpenAiCredentialIssueResponse issue(OpenAiCredentialIssueRequest request) {
        OpenAiProviderName providerName = OpenAiProviderName.from(request.getProviderName());
        String model = runtimePolicyService.requireAllowedModel(providerName, request.getModel());

        if (providerName.isUserManagedApiKeyProvider()) {
            return issueApiKeyCredential(request, providerName, model);
        }

        if (providerName.isCodexOAuthProvider()) {
            throw new CustomException(ErrorCode.OPENAI_PROVIDER_NOT_SUPPORTED);
        }

        if (providerName == OpenAiProviderName.OPENAI_DEV_FALLBACK) {
            runtimePolicyService.validateDevFallbackAvailable();
            return response(providerName, model, "api_key", properties.getApiKey(), null);
        }

        throw new CustomException(ErrorCode.OPENAI_PROVIDER_NOT_SUPPORTED);
    }

    private OpenAiCredentialIssueResponse issueApiKeyCredential(
        OpenAiCredentialIssueRequest request,
        OpenAiProviderName providerName,
        String model
    ) {
        return response(
            providerName,
            model,
            "api_key",
            openAiApiKeyService.resolveApiKey(request.getUserId(), providerName),
            null
        );
    }

    private OpenAiCredentialIssueResponse response(
        OpenAiProviderName providerName,
        String model,
        String credentialType,
        String credential,
        java.time.LocalDateTime expiresAt
    ) {
        return OpenAiCredentialIssueResponse.builder()
            .providerName(providerName.getValue())
            .authType(providerName.getAuthType())
            .model(model)
            .credentialType(credentialType)
            .credential(credential)
            .expiresAt(expiresAt)
            .build();
    }
}
