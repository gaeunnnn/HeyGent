package com.ssafy.heygent.domain.iot.repository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayEventType;
import com.ssafy.heygent.domain.iot.dto.DisplayIcon;
import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

@ExtendWith(MockitoExtension.class)
class DeviceDisplayStateRedisRepositoryTest {

    private static final Long USER_ID = 1L;
    private static final String ACTIVE_KEY = "iot:display:user:1:active";
    private static final Duration ACTIVE_TTL = Duration.ofMinutes(30);

    @Mock
    private RedisTemplate<String, String> redisTemplate;

    @Mock
    private ValueOperations<String, String> valueOperations;

    private ObjectMapper objectMapper;
    private DeviceDisplayStateRedisRepository repository;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        repository = new DeviceDisplayStateRedisRepository(redisTemplate, objectMapper);
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOperations);
    }

    @Test
    void saveTaskPayloadKeepsExistingTaskOrderWhenTaskIsUpdated() throws Exception {
        when(valueOperations.get(ACTIVE_KEY))
            .thenReturn(objectMapper.writeValueAsString(List.of("task-a", "task-b")));

        repository.saveTaskPayload(USER_ID, payload(DisplayEventType.STEP, "task-a", "날씨 확인"));

        List<String> activeTaskRunIds = capturedActiveTaskRunIds();

        assertThat(activeTaskRunIds).containsExactly("task-a", "task-b");
    }

    @Test
    void saveTaskPayloadAppendsNewTaskAfterExistingTasks() throws Exception {
        when(valueOperations.get(ACTIVE_KEY))
            .thenReturn(objectMapper.writeValueAsString(List.of("task-a", "task-b")));

        repository.saveTaskPayload(USER_ID, payload(DisplayEventType.STARTED, "task-c", "요청 확인"));

        List<String> activeTaskRunIds = capturedActiveTaskRunIds();

        assertThat(activeTaskRunIds).containsExactly("task-a", "task-b", "task-c");
    }

    @Test
    void saveTaskPayloadRemovesTerminalTaskFromActiveList() throws Exception {
        when(valueOperations.get(ACTIVE_KEY))
            .thenReturn(objectMapper.writeValueAsString(List.of("task-a", "task-b")));

        repository.saveTaskPayload(USER_ID, payload(DisplayEventType.DONE, "task-a", "성공!"));

        List<String> activeTaskRunIds = capturedActiveTaskRunIds();

        assertThat(activeTaskRunIds).containsExactly("task-b");
    }

    private List<String> capturedActiveTaskRunIds() throws Exception {
        ArgumentCaptor<String> valueCaptor = ArgumentCaptor.forClass(String.class);
        verify(valueOperations, times(1)).set(eq(ACTIVE_KEY), valueCaptor.capture(), eq(ACTIVE_TTL));
        return objectMapper.readValue(valueCaptor.getValue(), new TypeReference<>() {
        });
    }

    private DisplayEventPayload payload(DisplayEventType type, String taskRunId, String text) {
        return new DisplayEventPayload(
            type,
            "session-1",
            taskRunId,
            "step-1",
            DisplayIcon.INFO,
            text,
            "WORKING",
            3000L,
            10,
            "AUTO",
            "RUNNING",
            false,
            1L
        );
    }
}
