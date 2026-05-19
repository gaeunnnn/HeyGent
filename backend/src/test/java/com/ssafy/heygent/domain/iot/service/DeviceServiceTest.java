package com.ssafy.heygent.domain.iot.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.heygent.domain.iot.dto.DeviceRegisterRequest;
import com.ssafy.heygent.domain.iot.dto.DeviceResponse;
import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayEventType;
import com.ssafy.heygent.domain.iot.dto.DisplayIcon;
import com.ssafy.heygent.domain.iot.dto.DisplayPublishResult;
import com.ssafy.heygent.domain.iot.dto.DisplayPublishTestRequest;
import com.ssafy.heygent.domain.iot.entity.IotDevice;
import com.ssafy.heygent.domain.iot.entity.IotDeviceStatus;
import com.ssafy.heygent.domain.iot.repository.IotDeviceRepository;
import com.ssafy.heygent.domain.user.entity.User;
import com.ssafy.heygent.domain.user.repository.UserRepository;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

@ExtendWith(MockitoExtension.class)
class DeviceServiceTest {

    private static final Long USER_ID = 1L;
    private static final String DEVICE_ID = "heygent-c3-a1b2c3";

    @Mock
    private IotDeviceRepository iotDeviceRepository;

    @Mock
    private UserRepository userRepository;

    @Mock
    private DisplayEventMapper displayEventMapper;

    @Mock
    private MqttDisplayPublisher mqttDisplayPublisher;

    private DeviceService deviceService;

    @BeforeEach
    void setUp() {
        deviceService = new DeviceService(
            iotDeviceRepository,
            userRepository,
            displayEventMapper,
            mqttDisplayPublisher
        );
    }

    @Test
    void registerCreatesActiveDeviceWhenUserHasNoDevice() {
        User user = User.builder().id(USER_ID).kakaoId(12345L).build();
        IotDevice savedDevice = IotDevice.builder()
            .id(10L)
            .user(user)
            .deviceId(DEVICE_ID)
            .displayName("desk oled")
            .status(IotDeviceStatus.ACTIVE)
            .build();

        when(iotDeviceRepository.existsByDeviceId(DEVICE_ID)).thenReturn(false);
        when(iotDeviceRepository.existsByUserId(USER_ID)).thenReturn(false);
        when(userRepository.findById(USER_ID)).thenReturn(Optional.of(user));
        when(iotDeviceRepository.save(any(IotDevice.class))).thenReturn(savedDevice);

        DeviceResponse response = deviceService.register(
            USER_ID,
            new DeviceRegisterRequest(DEVICE_ID, "desk oled")
        );

        assertThat(response.deviceId()).isEqualTo(DEVICE_ID);
        assertThat(response.displayName()).isEqualTo("desk oled");
        assertThat(response.status()).isEqualTo(IotDeviceStatus.ACTIVE);
    }

    @Test
    void registerFailsWhenDeviceIdAlreadyExists() {
        when(iotDeviceRepository.existsByDeviceId(DEVICE_ID)).thenReturn(true);

        assertThatThrownBy(() -> deviceService.register(USER_ID, new DeviceRegisterRequest(DEVICE_ID, null)))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.DEVICE_ALREADY_PAIRED);

        verify(userRepository, never()).findById(USER_ID);
        verify(iotDeviceRepository, never()).save(any(IotDevice.class));
    }

    @Test
    void registerFailsWhenUserAlreadyHasDevice() {
        when(iotDeviceRepository.existsByDeviceId(DEVICE_ID)).thenReturn(false);
        when(iotDeviceRepository.existsByUserId(USER_ID)).thenReturn(true);

        assertThatThrownBy(() -> deviceService.register(USER_ID, new DeviceRegisterRequest(DEVICE_ID, null)))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.USER_DEVICE_LIMIT_EXCEEDED);

        verify(userRepository, never()).findById(USER_ID);
        verify(iotDeviceRepository, never()).save(any(IotDevice.class));
    }

    @Test
    void publishTestPublishesForActiveOwnedDevice() {
        IotDevice device = device(IotDeviceStatus.ACTIVE);
        DisplayPublishTestRequest request = request();
        DisplayEventPayload payload = payload();
        DisplayPublishResult expected = DisplayPublishResult.published(
            "devices/heygent-c3-a1b2c3/display",
            0,
            payload
        );

        when(iotDeviceRepository.findByDeviceIdAndUserId(DEVICE_ID, USER_ID)).thenReturn(Optional.of(device));
        when(displayEventMapper.toPayload(
            DisplayEventType.STEP,
            DisplayIcon.SEARCH,
            "session_test_001",
            "step_test_001",
            "searching"
        )).thenReturn(payload);
        when(mqttDisplayPublisher.publish(DEVICE_ID, payload)).thenReturn(expected);

        DisplayPublishResult result = deviceService.publishTest(USER_ID, DEVICE_ID, request);

        assertThat(result).isEqualTo(expected);
        verify(mqttDisplayPublisher).publish(DEVICE_ID, payload);
    }

    @Test
    void publishTestFailsForInactiveDevice() {
        when(iotDeviceRepository.findByDeviceIdAndUserId(DEVICE_ID, USER_ID))
            .thenReturn(Optional.of(device(IotDeviceStatus.INACTIVE)));

        assertThatThrownBy(() -> deviceService.publishTest(USER_ID, DEVICE_ID, request()))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.DEVICE_INACTIVE);

        verify(displayEventMapper, never()).toPayload(
            DisplayEventType.STEP,
            DisplayIcon.SEARCH,
            "session_test_001",
            "step_test_001",
            "searching"
        );
        verify(mqttDisplayPublisher, never()).publish(DEVICE_ID, payload());
    }

    @Test
    void publishTestFailsWhenDeviceIsNotOwnedByUser() {
        when(iotDeviceRepository.findByDeviceIdAndUserId(DEVICE_ID, USER_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> deviceService.publishTest(USER_ID, DEVICE_ID, request()))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND);

        verify(mqttDisplayPublisher, never()).publish(DEVICE_ID, payload());
    }

    @Test
    void unpairPublishesResetAndDeletesOwnedDevice() {
        IotDevice device = device(IotDeviceStatus.ACTIVE);
        DisplayEventPayload payload = resetPayload();
        when(iotDeviceRepository.findByDeviceIdAndUserId(DEVICE_ID, USER_ID)).thenReturn(Optional.of(device));
        when(displayEventMapper.toPayload(
            DisplayEventType.INFO,
            DisplayIcon.INFO,
            "pairing",
            "reset",
            "unpaired"
        )).thenReturn(payload);

        deviceService.unpair(USER_ID, DEVICE_ID);

        InOrder inOrder = inOrder(mqttDisplayPublisher, iotDeviceRepository);
        inOrder.verify(mqttDisplayPublisher).publish(DEVICE_ID, payload);
        inOrder.verify(iotDeviceRepository).delete(device);
    }

    @Test
    void unpairFailsWhenDeviceIsNotOwnedByUser() {
        when(iotDeviceRepository.findByDeviceIdAndUserId(DEVICE_ID, USER_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> deviceService.unpair(USER_ID, DEVICE_ID))
            .isInstanceOf(CustomException.class)
            .extracting("errorCode")
            .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND);

        verify(iotDeviceRepository, never()).delete(any(IotDevice.class));
        verify(displayEventMapper, never()).toPayload(
            DisplayEventType.INFO,
            DisplayIcon.INFO,
            "pairing",
            "reset",
            "unpaired"
        );
        verify(mqttDisplayPublisher, never()).publish(any(), any());
    }

    private DisplayPublishTestRequest request() {
        return new DisplayPublishTestRequest(
            DisplayEventType.STEP,
            DisplayIcon.SEARCH,
            "session_test_001",
            "step_test_001",
            "searching"
        );
    }

    private DisplayEventPayload payload() {
        return new DisplayEventPayload(
            DisplayEventType.STEP,
            "session_test_001",
            "step_test_001",
            DisplayIcon.SEARCH,
            "searching",
            3000L,
            12L
        );
    }

    private DisplayEventPayload resetPayload() {
        return new DisplayEventPayload(
            DisplayEventType.INFO,
            "pairing",
            "reset",
            DisplayIcon.INFO,
            "unpaired",
            3000L,
            13L
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
