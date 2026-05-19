package com.ssafy.heygent.domain.ai.openai.service;

import java.util.Map;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import com.ssafy.heygent.domain.ai.dto.response.OpenAiApiKeyConnectionResponse;
import com.ssafy.heygent.domain.ai.openai.client.OpenAiCredentialCacheClient;
import com.ssafy.heygent.domain.ai.openai.entity.OpenAiProviderConnection;
import com.ssafy.heygent.domain.ai.openai.model.OpenAiProviderName;
import com.ssafy.heygent.domain.ai.openai.repository.OpenAiProviderConnectionRepository;
import com.ssafy.heygent.domain.ai.openai.security.OpenAiCredentialCipher;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class OpenAiApiKeyService {

    private final OpenAiProviderConnectionRepository openAiProviderConnectionRepository;
    private final OpenAiCredentialCipher credentialCipher;
    private final OpenAiCredentialCacheClient credentialCacheClient;

    @Transactional
    public OpenAiApiKeyConnectionResponse upsert(Long userId, String apiKey) {
        return upsert(userId, OpenAiProviderName.OPENAI_API_KEY.getValue(), apiKey);
    }

    @Transactional
    public OpenAiApiKeyConnectionResponse upsert(Long userId, String providerNameValue, String apiKey) {
        if (!StringUtils.hasText(apiKey)) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
        OpenAiProviderName providerName = requireUserManagedApiKeyProvider(providerNameValue);

        OpenAiProviderConnection connection = findConnection(userId, providerName)
            .orElseGet(() -> OpenAiProviderConnection.builder()
                .userId(userId)
                .providerName(providerName.getValue())
                .build());

        connection.updateToken(
            "ApiKey",
            credentialCipher.encrypt(apiKey.trim()),
            null,
            "",
            null,
            Map.of("source", "user")
        );

        OpenAiProviderConnection saved = openAiProviderConnectionRepository.save(connection);
        invalidateCredentialCacheAfterCommit(userId, providerName);
        return OpenAiApiKeyConnectionResponse.builder()
            .providerName(providerName.getValue())
            .connected(true)
            .status("connected")
            .updatedAt(saved.getUpdatedAt())
            .build();
    }

    @Transactional
    public OpenAiApiKeyConnectionResponse delete(Long userId) {
        return delete(userId, OpenAiProviderName.OPENAI_API_KEY.getValue());
    }

    @Transactional
    public OpenAiApiKeyConnectionResponse delete(Long userId, String providerNameValue) {
        OpenAiProviderName providerName = requireUserManagedApiKeyProvider(providerNameValue);
        for (String lookupValue : providerName.lookupValues()) {
            openAiProviderConnectionRepository.deleteByUserIdAndProviderName(userId, lookupValue);
        }
        invalidateCredentialCacheAfterCommit(userId, providerName);

        return OpenAiApiKeyConnectionResponse.builder()
            .providerName(providerName.getValue())
            .connected(false)
            .status("disconnected")
            .updatedAt(null)
            .build();
    }

    @Transactional(readOnly = true)
    public String resolveApiKey(Long userId) {
        return resolveApiKey(userId, OpenAiProviderName.OPENAI_API_KEY);
    }

    @Transactional(readOnly = true)
    public String resolveApiKey(Long userId, OpenAiProviderName providerName) {
        OpenAiProviderConnection connection = findConnection(userId, providerName)
            .orElseThrow(() -> new CustomException(ErrorCode.OPENAI_PROVIDER_NOT_CONNECTED));
        return credentialCipher.decrypt(connection.getEncryptedAccessToken());
    }

    private OpenAiProviderName requireUserManagedApiKeyProvider(String providerNameValue) {
        OpenAiProviderName providerName = OpenAiProviderName.from(providerNameValue);
        if (!providerName.isUserManagedApiKeyProvider()) {
            throw new CustomException(ErrorCode.OPENAI_PROVIDER_NOT_SUPPORTED);
        }
        return providerName;
    }

    private java.util.Optional<OpenAiProviderConnection> findConnection(Long userId, OpenAiProviderName providerName) {
        for (String lookupValue : providerName.lookupValues()) {
            java.util.Optional<OpenAiProviderConnection> connection =
                openAiProviderConnectionRepository.findByUserIdAndProviderName(userId, lookupValue);
            if (connection.isPresent()) {
                return connection;
            }
        }
        return java.util.Optional.empty();
    }

    private void invalidateCredentialCacheAfterCommit(Long userId, OpenAiProviderName providerName) {
        Runnable invalidate = () -> credentialCacheClient.invalidate(userId, providerName.getValue());
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            invalidate.run();
            return;
        }

        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                // openai_provider_connections 변경이 실제 DB commit까지 끝난 뒤에만 AI cache를 지운다.
                // commit 전에 지우면 동시에 들어온 모델 호출이 아직 이전 DB 값을 다시 발급받아
                // 캐시를 되살릴 수 있으므로, 저장/삭제 트랜잭션의 성공 이후로 순서를 고정한다.
                invalidate.run();
            }
        });
    }
}
