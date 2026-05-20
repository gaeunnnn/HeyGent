package com.ssafy.heygent.domain.mattermost.service;

import java.net.URI;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import com.ssafy.heygent.domain.mattermost.dto.MattermostChannelCreateRequest;
import com.ssafy.heygent.domain.mattermost.dto.MattermostChannelResponse;
import com.ssafy.heygent.domain.mattermost.dto.MattermostChannelUpdateRequest;
import com.ssafy.heygent.domain.mattermost.dto.MattermostMessageRequest;
import com.ssafy.heygent.domain.mattermost.dto.MattermostMessageResponse;
import com.ssafy.heygent.domain.mattermost.dto.MattermostWebhookRequest;
import com.ssafy.heygent.domain.mattermost.dto.MattermostWebhookResponse;
import com.ssafy.heygent.domain.mattermost.entity.MattermostChannel;
import com.ssafy.heygent.domain.mattermost.repository.MattermostChannelRepository;
import com.ssafy.heygent.domain.user.entity.User;
import com.ssafy.heygent.domain.user.repository.UserRepository;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class MattermostService {

    static final String HEYGENT_MESSAGE_HEADER = "# :ai: HeyGent에서 온 메시지 입니다 :ai:";

    private final RestTemplate restTemplate = new RestTemplate();
    private final MattermostChannelRepository mattermostChannelRepository;
    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public List<MattermostChannelResponse> listChannels(Long userId) {
        return mattermostChannelRepository.findAllByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(MattermostChannelResponse::from)
                .toList();
    }

    @Transactional
    public MattermostChannelResponse createChannel(Long userId, MattermostChannelCreateRequest request) {
        String alias = normalizeAlias(request.alias());
        if (mattermostChannelRepository.existsByUserIdAndAliasIgnoreCase(userId, alias)) {
            throw new CustomException(ErrorCode.MATTERMOST_CHANNEL_ALIAS_DUPLICATE);
        }

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        boolean firstChannel = mattermostChannelRepository.findAllByUserIdOrderByCreatedAtDesc(userId).isEmpty();
        boolean defaultChannel = firstChannel || request.defaultChannel();
        if (defaultChannel) {
            unsetDefaultChannels(userId);
        }

        MattermostChannel channel = mattermostChannelRepository.save(MattermostChannel.builder()
                .user(user)
                .alias(alias)
                .displayName(displayNameOrAlias(request.displayName(), alias))
                .webhookUrl(validateWebhookUrl(request.webhookUrl()).toString())
                .defaultChannel(defaultChannel)
                .build());
        return MattermostChannelResponse.from(channel);
    }

    @Transactional
    public MattermostChannelResponse updateChannel(Long userId, Long channelId, MattermostChannelUpdateRequest request) {
        MattermostChannel channel = findChannel(userId, channelId);
        String alias = normalizeAlias(request.alias());
        mattermostChannelRepository.findByUserIdAndAliasIgnoreCase(userId, alias)
                .filter(existing -> !existing.getId().equals(channelId))
                .ifPresent(existing -> {
                    throw new CustomException(ErrorCode.MATTERMOST_CHANNEL_ALIAS_DUPLICATE);
                });

        String webhookUrl = null;
        if (request.webhookUrl() != null && !request.webhookUrl().isBlank()) {
            webhookUrl = validateWebhookUrl(request.webhookUrl()).toString();
        }
        channel.update(alias, displayNameOrAlias(request.displayName(), alias), webhookUrl);
        if (request.defaultChannel()) {
            unsetDefaultChannels(userId);
            channel.markDefault(true);
        }
        return MattermostChannelResponse.from(channel);
    }

    @Transactional
    public MattermostChannelResponse setDefaultChannel(Long userId, Long channelId) {
        MattermostChannel channel = findChannel(userId, channelId);
        unsetDefaultChannels(userId);
        channel.markDefault(true);
        return MattermostChannelResponse.from(channel);
    }

    @Transactional
    public void deleteChannel(Long userId, Long channelId) {
        MattermostChannel channel = findChannel(userId, channelId);
        boolean wasDefault = channel.isDefaultChannel();
        mattermostChannelRepository.delete(channel);
        if (wasDefault) {
            mattermostChannelRepository.findAllByUserIdOrderByCreatedAtDesc(userId).stream()
                    .findFirst()
                    .ifPresent(nextDefault -> nextDefault.markDefault(true));
        }
    }

    @Transactional(readOnly = true)
    public MattermostMessageResponse sendMessage(Long userId, MattermostMessageRequest request) {
        MattermostChannel channel = resolveTargetChannel(userId, request.target());
        postWebhook(validateWebhookUrl(channel.getWebhookUrl()), request.message());
        return new MattermostMessageResponse(true, channel.getAlias(), channel.getDisplayName());
    }

    public MattermostWebhookResponse sendWebhook(MattermostWebhookRequest request) {
        URI webhookUri = validateWebhookUrl(request.getWebhookUrl());
        postWebhook(webhookUri, request.getMessage());
        return MattermostWebhookResponse.builder()
                .sent(true)
                .build();
    }

    private void postWebhook(URI webhookUri, String message) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            restTemplate.postForEntity(
                    webhookUri,
                    new HttpEntity<>(Map.of("text", withHeygentHeader(message)), headers),
                    String.class
            );
        } catch (RestClientException | IllegalArgumentException exception) {
            throw new CustomException(ErrorCode.MATTERMOST_REQUEST_FAILED);
        }
    }

    static String withHeygentHeader(String message) {
        String trimmed = message.trim();
        if (trimmed.startsWith(HEYGENT_MESSAGE_HEADER)) {
            return trimmed;
        }
        return HEYGENT_MESSAGE_HEADER + "\n\n" + trimmed;
    }

    private MattermostChannel findChannel(Long userId, Long channelId) {
        return mattermostChannelRepository.findByIdAndUserId(channelId, userId)
                .orElseThrow(() -> new CustomException(ErrorCode.MATTERMOST_CHANNEL_NOT_FOUND));
    }

    private MattermostChannel resolveTargetChannel(Long userId, String target) {
        if (target != null && !target.isBlank()) {
            return mattermostChannelRepository.findByUserIdAndAliasIgnoreCase(userId, normalizeAlias(target))
                    .orElseThrow(() -> new CustomException(ErrorCode.MATTERMOST_CHANNEL_NOT_FOUND));
        }
        return mattermostChannelRepository.findByUserIdAndDefaultChannelTrue(userId)
                .orElseThrow(() -> new CustomException(ErrorCode.MATTERMOST_CHANNEL_NOT_CONFIGURED));
    }

    private void unsetDefaultChannels(Long userId) {
        mattermostChannelRepository.findAllByUserIdOrderByCreatedAtDesc(userId)
                .forEach(channel -> channel.markDefault(false));
    }

    private String normalizeAlias(String alias) {
        return alias.trim().toLowerCase(Locale.ROOT);
    }

    private String displayNameOrAlias(String displayName, String alias) {
        if (displayName == null || displayName.isBlank()) {
            return alias;
        }
        return displayName.trim();
    }

    private URI validateWebhookUrl(String webhookUrl) {
        String trimmed = webhookUrl.trim();
        if (!trimmed.startsWith("https://") && !trimmed.startsWith("http://")) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
        URI uri;
        try {
            uri = URI.create(trimmed);
        } catch (IllegalArgumentException exception) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
        if (uri.getHost() == null || !uri.getPath().startsWith("/hooks/")) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
        return uri;
    }
}
