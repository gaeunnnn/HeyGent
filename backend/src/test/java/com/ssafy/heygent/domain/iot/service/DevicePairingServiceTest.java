package com.ssafy.heygent.domain.iot.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.heygent.domain.iot.dto.DevicePairRequest;
import com.ssafy.heygent.domain.iot.dto.DevicePairingSession;
import com.ssafy.heygent.domain.iot.dto.DevicePairingStatusResponse;
import com.ssafy.heygent.domain.iot.dto.DeviceResponse;
import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayEventType;
import com.ssafy.heygent.domain.iot.dto.DisplayIcon;
import com.ssafy.heygent.domain.iot.dto.DisplayPairingStartRequest;
import com.ssafy.heygent.domain.iot.dto.DisplayPairingStartResponse;
import com.ssafy.heygent.domain.iot.dto.DisplayPublishResult;
import com.ssafy.heygent.domain.iot.entity.IotDevice;
import com.ssafy.heygent.domain.iot.entity.IotDeviceStatus;
import com.ssafy.heygent.domain.iot.repository.DevicePairingRedisRepository;
import com.ssafy.heygent.domain.iot.repository.IotDeviceRepository;
import com.ssafy.heygent.domain.user.entity.User;
import com.ssafy.heygent.domain.user.repository.UserRepository;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Optional;

@ExtendWith(MockitoExtension.class)
class DevicePairingServiceTest {

    private static final Long USER_ID = 1L;
    private static final String DEVICE_ID = "heygent-c3-a1b2c3";

    @Mock
    private DevicePairingRedisRepository pairingRedisRepository;

    @Mock
    private IotDeviceRepository iotDeviceRepository;

    @Mock
    private UserRepository userRepository;

    @Mock
    private DisplayEventMapper displayEventMapper;

    @Mock
    private MqttDisplayPublisher mqttDisplayPublisher;

    private DevicePairingService service;

    @BeforeEach
    void setUp() {
        service = new DevicePairingService(
            pairingRedisRepository,
            iotDeviceRepository,
            userRepository,
            displayEventMapper,
            mqttDisplayPublisher
        );
    }

    @Test
    void startCreatesPendingSession() {
        when(iotDeviceRepository.existsByDeviceId(DEVICE_ID)).thenReturn(false);
        when(pairingRedisRepository.findByDeviceId(DEVICE_ID)).thenReturn(Optional.empty());
        when(pairingRedisRepository.existsByCode(any())).thenReturn(false);

        DisplayPairingStartResponse response = service.start(new DisplayPairingStartRequest(
            " " + DEVICE_ID + " ",
            " nonce-001 ",
            " 0.1.0 "
        ));

        assertThat(response.pairCode()).matches("\\d{6}");
        assertThat(response.expiresInSeconds()).isEqualTo(300L);

        ArgumentCaptor<DevicePairingSession> sessionCaptor = ArgumentCaptor.forClass(DevicePairingSession.class);
        verify(pairingRedisRepository).savePendingSession(eq(response.pairCode()), sessionCaptor.capture(),
            eq(Duration.ofMinutes(5)));
        assertThat(sessionCaptor.getValue().deviceId()).isEqualTo(DEVICE_ID);
        assertThat(sessionCaptor.getValue().nonce()).isEqualTo("nonce-001");
        assertThat(sessionCaptor.getValue().firmwareVersion()).isEqualTo("0.1.0");
    }

    @Test
    void startFailsWhenDeviceIsAlreadyPaired() {
        when(iotDeviceRepository.existsByDeviceId(DEVICE_ID)).thenReturn(true);

        assertThatThrownBy(() -> service.start(new DisplayPairingStartRequest(DEVICE_ID, null, null)))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.DEVICE_ALREADY_PAIRED);
    }

    @Test
    void pairCreatesDeviceAndPublishesConnectedPayload() {
        DevicePairingSession session = session("482913", LocalDateTime.now().plusMinutes(5));
        User user = User.builder().id(USER_ID).kakaoId(12345L).build();
        IotDevice savedDevice = IotDevice.builder()
            .id(10L)
            .user(user)
            .deviceId(DEVICE_ID)
            .displayName("desk oled")
            .status(IotDeviceStatus.ACTIVE)
            .build();
        DisplayEventPayload payload = new DisplayEventPayload(
            DisplayEventType.INFO,
            "pairing",
            "pairing",
            DisplayIcon.SUCCESS,
            "connected",
            3000L,
            1L
        );

        when(pairingRedisRepository.findByCode("482913")).thenReturn(Optional.of(session));
        when(iotDeviceRepository.existsByDeviceId(DEVICE_ID)).thenReturn(false);
        when(iotDeviceRepository.existsByUserId(USER_ID)).thenReturn(false);
        when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));
        when(iotDeviceRepository.save(any(IotDevice.class))).thenReturn(savedDevice);
        when(displayEventMapper.toPayload(DisplayEventType.INFO, DisplayIcon.SUCCESS, "pairing", "pairing",
            "connected")).thenReturn(payload);
        when(mqttDisplayPublisher.publish(DEVICE_ID, payload))
            .thenReturn(DisplayPublishResult.published("devices/" + DEVICE_ID + "/display", 0, payload));

        DeviceResponse response = service.pair(USER_ID, new DevicePairRequest("482913", "desk oled"));

        assertThat(response.deviceId()).isEqualTo(DEVICE_ID);
        assertThat(response.displayName()).isEqualTo("desk oled");
        verify(pairingRedisRepository).deleteByCodeAndDeviceId("482913", DEVICE_ID);
        verify(mqttDisplayPublisher).publish(DEVICE_ID, payload);
    }

    @Test
    void pairFailsWhenCodeIsMissing() {
        when(pairingRedisRepository.findByCode("482913")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.pair(USER_ID, new DevicePairRequest("482913", null)))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.PAIR_CODE_NOT_FOUND);
    }

    @Test
    void pairFailsWhenCodeIsExpired() {
        DevicePairingSession session = session("482913", LocalDateTime.now().minusSeconds(1));
        when(pairingRedisRepository.findByCode("482913")).thenReturn(Optional.of(session));

        assertThatThrownBy(() -> service.pair(USER_ID, new DevicePairRequest("482913", null)))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.PAIR_CODE_EXPIRED);

        verify(pairingRedisRepository).deleteByCodeAndDeviceId("482913", DEVICE_ID);
    }

    @Test
    void statusReturnsPairedWhenDeviceExists() {
        IotDevice device = IotDevice.builder()
            .user(User.builder().id(USER_ID).kakaoId(12345L).build())
            .deviceId(DEVICE_ID)
            .displayName("desk oled")
            .status(IotDeviceStatus.ACTIVE)
            .build();
        when(iotDeviceRepository.findByDeviceId(DEVICE_ID)).thenReturn(Optional.of(device));

        DevicePairingStatusResponse response = service.status(" " + DEVICE_ID + " ");

        assertThat(response.deviceId()).isEqualTo(DEVICE_ID);
        assertThat(response.paired()).isTrue();
        assertThat(response.status()).isEqualTo("ACTIVE");
    }

    @Test
    void statusReturnsUnpairedWhenDeviceDoesNotExist() {
        when(iotDeviceRepository.findByDeviceId(DEVICE_ID)).thenReturn(Optional.empty());

        DevicePairingStatusResponse response = service.status(DEVICE_ID);

        assertThat(response.deviceId()).isEqualTo(DEVICE_ID);
        assertThat(response.paired()).isFalse();
        assertThat(response.status()).isEqualTo("UNPAIRED");
    }

    private DevicePairingSession session(String pairCode, LocalDateTime expiresAt) {
        LocalDateTime createdAt = expiresAt.minusMinutes(5);
        return DevicePairingSession.pending(
            pairCode,
            DEVICE_ID,
            "nonce-001",
            "0.1.0",
            createdAt,
            expiresAt
        );
    }
}
