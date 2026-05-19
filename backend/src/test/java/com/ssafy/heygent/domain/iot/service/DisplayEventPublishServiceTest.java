package com.ssafy.heygent.domain.iot.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayEventType;
import com.ssafy.heygent.domain.iot.dto.DisplayIcon;
import com.ssafy.heygent.domain.iot.dto.DisplayPublishResult;
import com.ssafy.heygent.domain.iot.entity.IotDevice;
import com.ssafy.heygent.domain.iot.entity.IotDeviceStatus;
import com.ssafy.heygent.domain.iot.repository.IotDeviceRepository;
import com.ssafy.heygent.domain.user.entity.User;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

@ExtendWith(MockitoExtension.class)
class DisplayEventPublishServiceTest {

    private static final Long USER_ID = 1L;
    private static final String DEVICE_ID = "heygent-c3-a1b2c3";
    private static final String SESSION_ID = "session_test_001";
    private static final String STEP_RUN_ID = "step_test_001";

    @Mock
    private IotDeviceRepository iotDeviceRepository;

    @Mock
    private DisplayEventMapper displayEventMapper;

    @Mock
    private MqttDisplayPublisher mqttDisplayPublisher;

    private DisplayEventPublishService displayEventPublishService;

    @BeforeEach
    void setUp() {
        displayEventPublishService = new DisplayEventPublishService(
            iotDeviceRepository,
            displayEventMapper,
            mqttDisplayPublisher
        );
    }

    @Test
    void publishSkipsWhenUserHasNoDevice() {
        DisplayEventPayload payload = payload();
        when(displayEventMapper.toPayload(
            DisplayEventType.STEP,
            DisplayIcon.SEARCH,
            SESSION_ID,
            STEP_RUN_ID,
            "searching"
        )).thenReturn(payload);
        when(iotDeviceRepository.findByUserId(USER_ID)).thenReturn(Optional.empty());

        DisplayPublishResult result = displayEventPublishService.publish(
            USER_ID,
            DisplayEventType.STEP,
            DisplayIcon.SEARCH,
            SESSION_ID,
            STEP_RUN_ID,
            "searching"
        );

        assertThat(result.published()).isFalse();
        assertThat(result.reason()).isEqualTo("IoT device not found");
        assertThat(result.payload()).isEqualTo(payload);
        verify(mqttDisplayPublisher, never()).publish(DEVICE_ID, payload);
    }

    @Test
    void publishSkipsWhenDeviceIsInactive() {
        DisplayEventPayload payload = payload();
        when(iotDeviceRepository.findByUserId(USER_ID)).thenReturn(Optional.of(device(IotDeviceStatus.INACTIVE)));

        DisplayPublishResult result = displayEventPublishService.publish(USER_ID, payload);

        assertThat(result.published()).isFalse();
        assertThat(result.reason()).isEqualTo("IoT device inactive");
        assertThat(result.payload()).isEqualTo(payload);
        verify(mqttDisplayPublisher, never()).publish(DEVICE_ID, payload);
    }

    @Test
    void publishSendsPayloadToActiveDevice() {
        DisplayEventPayload payload = payload();
        DisplayPublishResult expected = DisplayPublishResult.published(
            "devices/heygent-c3-a1b2c3/display",
            0,
            payload
        );
        when(iotDeviceRepository.findByUserId(USER_ID)).thenReturn(Optional.of(device(IotDeviceStatus.ACTIVE)));
        when(mqttDisplayPublisher.publish(DEVICE_ID, payload)).thenReturn(expected);

        DisplayPublishResult result = displayEventPublishService.publish(USER_ID, payload);

        assertThat(result).isEqualTo(expected);
        verify(mqttDisplayPublisher).publish(DEVICE_ID, payload);
    }

    @Test
    void publishReturnsPublisherFailureResult() {
        DisplayEventPayload payload = payload();
        DisplayPublishResult expected = DisplayPublishResult.skipped(
            "MQTT publish failed",
            "devices/heygent-c3-a1b2c3/display",
            0,
            payload
        );
        when(iotDeviceRepository.findByUserId(USER_ID)).thenReturn(Optional.of(device(IotDeviceStatus.ACTIVE)));
        when(mqttDisplayPublisher.publish(DEVICE_ID, payload)).thenReturn(expected);

        DisplayPublishResult result = displayEventPublishService.publish(USER_ID, payload);

        assertThat(result).isEqualTo(expected);
        assertThat(result.reason()).isEqualTo("MQTT publish failed");
    }

    private DisplayEventPayload payload() {
        return new DisplayEventPayload(
            DisplayEventType.STEP,
            SESSION_ID,
            STEP_RUN_ID,
            DisplayIcon.SEARCH,
            "searching",
            3000L,
            12L
        );
    }

    private IotDevice device(IotDeviceStatus status) {
        return IotDevice.builder()
            .user(User.builder().id(USER_ID).kakaoId(12345L).build())
            .deviceId(DEVICE_ID)
            .displayName("desk oled")
            .status(status)
            .build();
    }
}
