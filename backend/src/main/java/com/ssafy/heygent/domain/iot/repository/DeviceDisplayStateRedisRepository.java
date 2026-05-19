package com.ssafy.heygent.domain.iot.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayFocusState;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

@Repository
@RequiredArgsConstructor
public class DeviceDisplayStateRedisRepository {

    private static final String ACTIVE_KEY_PREFIX = "iot:display:user:";
    private static final String TASK_KEY_PREFIX = "iot:display:task:";
    private static final Duration ACTIVE_TTL = Duration.ofMinutes(30);
    private static final Duration TASK_TTL = Duration.ofMinutes(30);
    private static final Duration LAST_SENT_TTL = Duration.ofMinutes(10);

    private final RedisTemplate<String, String> redisTemplate;
    private final ObjectMapper objectMapper;

    public void saveTaskPayload(Long userId, DisplayEventPayload payload) {
        if (!StringUtils.hasText(payload.taskRunId())) {
            return;
        }
        redisTemplate.opsForValue().set(taskKey(payload.taskRunId()), serialize(payload), TASK_TTL);
        refreshActiveTask(userId, payload);
    }

    public List<DisplayEventPayload> listActivePayloads(Long userId) {
        return activeTaskRunIds(userId).stream()
            .map(this::findTaskPayload)
            .flatMap(Optional::stream)
            .toList();
    }

    public Optional<DisplayEventPayload> findTaskPayload(String taskRunId) {
        if (!StringUtils.hasText(taskRunId)) {
            return Optional.empty();
        }
        String value = redisTemplate.opsForValue().get(taskKey(taskRunId));
        if (value == null) {
            return Optional.empty();
        }
        return Optional.of(deserialize(value, DisplayEventPayload.class));
    }

    public void saveFocus(Long userId, DisplayFocusState focusState, Duration ttl) {
        redisTemplate.opsForValue().set(focusKey(userId), serialize(focusState), ttl);
    }

    public Optional<DisplayFocusState> findFocus(Long userId) {
        String value = redisTemplate.opsForValue().get(focusKey(userId));
        if (value == null) {
            return Optional.empty();
        }
        return Optional.of(deserialize(value, DisplayFocusState.class));
    }

    public Optional<String> findLastSentHash(Long userId) {
        return Optional.ofNullable(redisTemplate.opsForValue().get(lastSentKey(userId)));
    }

    public void saveLastSentHash(Long userId, String hash) {
        redisTemplate.opsForValue().set(lastSentKey(userId), hash, LAST_SENT_TTL);
    }

    private void refreshActiveTask(Long userId, DisplayEventPayload payload) {
        if (!StringUtils.hasText(payload.taskRunId())) {
            return;
        }

        List<String> taskRunIds = new ArrayList<>(activeTaskRunIds(userId));

        if (isTerminal(payload)) {
            taskRunIds.remove(payload.taskRunId());
            saveActiveTaskRunIds(userId, taskRunIds);
            return;
        }

        if (!taskRunIds.contains(payload.taskRunId())) {
            taskRunIds.add(payload.taskRunId());
        }
        saveActiveTaskRunIds(userId, taskRunIds);
    }

    private boolean isTerminal(DisplayEventPayload payload) {
        return switch (payload.type()) {
            case DONE, FAILED, CANCELED -> true;
            case STARTED, STEP, WAITING, INFO -> false;
        };
    }

    private List<String> activeTaskRunIds(Long userId) {
        String value = redisTemplate.opsForValue().get(activeKey(userId));
        if (value == null) {
            return List.of();
        }
        try {
            return objectMapper.readValue(value, new TypeReference<>() {});
        } catch (JsonProcessingException exception) {
            throw new CustomException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
    }

    private void saveActiveTaskRunIds(Long userId, List<String> taskRunIds) {
        redisTemplate.opsForValue().set(activeKey(userId), serialize(taskRunIds), ACTIVE_TTL);
    }

    private String serialize(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new CustomException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
    }

    private <T> T deserialize(String value, Class<T> type) {
        try {
            return objectMapper.readValue(value, type);
        } catch (JsonProcessingException exception) {
            throw new CustomException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
    }

    private String activeKey(Long userId) {
        return ACTIVE_KEY_PREFIX + userId + ":active";
    }

    private String focusKey(Long userId) {
        return ACTIVE_KEY_PREFIX + userId + ":focus";
    }

    private String lastSentKey(Long userId) {
        return ACTIVE_KEY_PREFIX + userId + ":last-sent";
    }

    private String taskKey(String taskRunId) {
        return TASK_KEY_PREFIX + taskRunId;
    }
}
