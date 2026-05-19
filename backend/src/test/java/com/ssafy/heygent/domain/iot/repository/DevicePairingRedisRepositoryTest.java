package com.ssafy.heygent.domain.iot.repository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.ssafy.heygent.domain.iot.dto.DevicePairingSession;
import com.ssafy.heygent.domain.iot.dto.DevicePairingStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@ExtendWith(MockitoExtension.class)
class DevicePairingRedisRepositoryTest {

    private static final String PAIR_CODE = "482913";
    private static final String DEVICE_ID = "heygent-c3-a1b2c3";

    @Mock
    private RedisTemplate<String, String> redisTemplate;

    @Mock
    private ValueOperations<String, String> valueOperations;

    private ObjectMapper objectMapper;
    private DevicePairingRedisRepository repository;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        objectMapper.registerModule(new JavaTimeModule());
        repository = new DevicePairingRedisRepository(redisTemplate, objectMapper);
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOperations);
    }

    @Test
    void savePendingSessionStoresCodeAndDeviceKeysWithSameTtl() {
        Duration ttl = Duration.ofMinutes(5);
        DevicePairingSession session = session();

        repository.savePendingSession(PAIR_CODE, session, ttl);

        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> valueCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Duration> ttlCaptor = ArgumentCaptor.forClass(Duration.class);
        verify(valueOperations, times(2)).set(keyCaptor.capture(), valueCaptor.capture(), ttlCaptor.capture());

        assertThat(keyCaptor.getAllValues()).containsExactly(
            "iot:pairing:code:482913",
            "iot:pairing:device:heygent-c3-a1b2c3"
        );
        assertThat(ttlCaptor.getAllValues()).containsExactly(ttl, ttl);
    }

    @Test
    void findByCodeReturnsStoredSession() throws Exception {
        when(valueOperations.get("iot:pairing:code:482913")).thenReturn(objectMapper.writeValueAsString(session()));

        Optional<DevicePairingSession> result = repository.findByCode(PAIR_CODE);

        assertThat(result).isPresent();
        assertThat(result.get().pairCode()).isEqualTo(PAIR_CODE);
        assertThat(result.get().deviceId()).isEqualTo(DEVICE_ID);
        assertThat(result.get().status()).isEqualTo(DevicePairingStatus.PENDING);
    }

    @Test
    void deleteByCodeAndDeviceIdDeletesBothKeys() {
        repository.deleteByCodeAndDeviceId(PAIR_CODE, DEVICE_ID);

        verify(redisTemplate).delete(List.of(
            "iot:pairing:code:482913",
            "iot:pairing:device:heygent-c3-a1b2c3"
        ));
    }

    private DevicePairingSession session() {
        LocalDateTime createdAt = LocalDateTime.of(2026, 5, 5, 20, 0);
        return DevicePairingSession.pending(
            PAIR_CODE,
            DEVICE_ID,
            "nonce-001",
            "0.1.0",
            createdAt,
            createdAt.plusMinutes(5)
        );
    }
}
