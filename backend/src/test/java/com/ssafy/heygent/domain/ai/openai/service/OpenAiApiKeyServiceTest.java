package com.ssafy.heygent.domain.ai.openai.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import com.ssafy.heygent.domain.ai.dto.response.OpenAiApiKeyConnectionResponse;
import com.ssafy.heygent.domain.ai.openai.client.OpenAiCredentialCacheClient;
import com.ssafy.heygent.domain.ai.openai.entity.OpenAiProviderConnection;
import com.ssafy.heygent.domain.ai.openai.model.OpenAiProviderName;
import com.ssafy.heygent.domain.ai.openai.repository.OpenAiProviderConnectionRepository;
import com.ssafy.heygent.domain.ai.openai.security.OpenAiCredentialCipher;

@ExtendWith(MockitoExtension.class)
class OpenAiApiKeyServiceTest {

    @Mock
    private OpenAiProviderConnectionRepository openAiProviderConnectionRepository;

    @Mock
    private OpenAiCredentialCipher credentialCipher;

    @Mock
    private OpenAiCredentialCacheClient credentialCacheClient;

    private OpenAiApiKeyService openAiApiKeyService;

    @BeforeEach
    void setUp() {
        openAiApiKeyService = new OpenAiApiKeyService(
            openAiProviderConnectionRepository,
            credentialCipher,
            credentialCacheClient
        );
    }

    @Test
    void upsertEncryptsAndStoresUserApiKey() {
        when(openAiProviderConnectionRepository.findByUserIdAndProviderName(
            1L,
            OpenAiProviderName.OPENAI_API_KEY.getValue()
        )).thenReturn(Optional.empty());
        when(credentialCipher.encrypt("sk-test")).thenReturn("encrypted");
        when(openAiProviderConnectionRepository.save(any(OpenAiProviderConnection.class)))
            .thenAnswer(invocation -> invocation.getArgument(0));

        OpenAiApiKeyConnectionResponse response = openAiApiKeyService.upsert(1L, " sk-test ");

        ArgumentCaptor<OpenAiProviderConnection> captor = ArgumentCaptor.forClass(OpenAiProviderConnection.class);
        verify(openAiProviderConnectionRepository).save(captor.capture());
        assertThat(captor.getValue().getProviderName()).isEqualTo("openai_api_key");
        assertThat(captor.getValue().getEncryptedAccessToken()).isEqualTo("encrypted");
        assertThat(response.isConnected()).isTrue();
        verify(credentialCacheClient).invalidate(1L, "openai_api_key");
    }

    @Test
    void upsertEncryptsAndStoresGeminiApiKey() {
        when(openAiProviderConnectionRepository.findByUserIdAndProviderName(
            1L,
            OpenAiProviderName.GEMINI_API_KEY.getValue()
        )).thenReturn(Optional.empty());
        when(credentialCipher.encrypt("gemini-key")).thenReturn("encrypted-gemini");
        when(openAiProviderConnectionRepository.save(any(OpenAiProviderConnection.class)))
            .thenAnswer(invocation -> invocation.getArgument(0));

        OpenAiApiKeyConnectionResponse response =
            openAiApiKeyService.upsert(1L, "gemini_api_key", " gemini-key ");

        ArgumentCaptor<OpenAiProviderConnection> captor = ArgumentCaptor.forClass(OpenAiProviderConnection.class);
        verify(openAiProviderConnectionRepository).save(captor.capture());
        assertThat(captor.getValue().getProviderName()).isEqualTo("gemini_api_key");
        assertThat(captor.getValue().getEncryptedAccessToken()).isEqualTo("encrypted-gemini");
        assertThat(response.getProviderName()).isEqualTo("gemini_api_key");
        assertThat(response.isConnected()).isTrue();
        verify(credentialCacheClient).invalidate(1L, "gemini_api_key");
    }

    @Test
    void deleteDisconnectsUserApiKeyProvider() {
        OpenAiApiKeyConnectionResponse response = openAiApiKeyService.delete(1L);

        verify(openAiProviderConnectionRepository).deleteByUserIdAndProviderName(
            1L,
            OpenAiProviderName.OPENAI_API_KEY.getValue()
        );
        verify(openAiProviderConnectionRepository).deleteByUserIdAndProviderName(1L, "openai_user_api_key");
        assertThat(response.isConnected()).isFalse();
        verify(credentialCacheClient).invalidate(1L, "openai_api_key");
    }
}
