package com.ssafy.heygent.domain.iot.dto;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

class DevicePairingContractTest {

    private Validator validator;

    @BeforeEach
    void setUp() {
        validator = Validation.buildDefaultValidatorFactory().getValidator();
    }

    @Test
    void startRequestAcceptsDeviceIdentity() {
        DisplayPairingStartRequest request = new DisplayPairingStartRequest(
            "heygent-c3-a1b2c3",
            "nonce-001",
            "0.1.0"
        );

        assertThat(validator.validate(request)).isEmpty();
    }

    @Test
    void startRequestRequiresDeviceId() {
        DisplayPairingStartRequest request = new DisplayPairingStartRequest(
            "",
            "nonce-001",
            "0.1.0"
        );

        assertThat(validator.validate(request)).isNotEmpty();
    }

    @Test
    void startRequestRequiresHeygentDeviceIdentity() {
        DisplayPairingStartRequest request = new DisplayPairingStartRequest(
            "deskmate-c3-a1b2c3",
            "nonce-001",
            "0.1.0"
        );

        assertThat(validator.validate(request)).isNotEmpty();
    }

    @Test
    void registerRequestRequiresHeygentDeviceIdentity() {
        DeviceRegisterRequest validRequest = new DeviceRegisterRequest("heygent-c3-a1b2c3", "HeyGent");
        DeviceRegisterRequest invalidRequest = new DeviceRegisterRequest("esp32c3-oled-001", "HeyGent");

        assertThat(validator.validate(validRequest)).isEmpty();
        assertThat(validator.validate(invalidRequest)).isNotEmpty();
    }

    @Test
    void pairRequestRequiresSixDigitPairCode() {
        DevicePairRequest validRequest = new DevicePairRequest("482913", "desk oled");
        DevicePairRequest invalidRequest = new DevicePairRequest("48291A", "desk oled");

        assertThat(validator.validate(validRequest)).isEmpty();
        assertThat(validator.validate(invalidRequest)).isNotEmpty();
    }

    @Test
    void sessionFactoryCreatesPendingSession() {
        LocalDateTime createdAt = LocalDateTime.of(2026, 5, 5, 20, 0);
        LocalDateTime expiresAt = createdAt.plusMinutes(5);

        DevicePairingSession session = DevicePairingSession.pending(
            "482913",
            "heygent-c3-a1b2c3",
            "nonce-001",
            "0.1.0",
            createdAt,
            expiresAt
        );

        assertThat(session.status()).isEqualTo(DevicePairingStatus.PENDING);
        assertThat(session.pairCode()).isEqualTo("482913");
        assertThat(session.deviceId()).isEqualTo("heygent-c3-a1b2c3");
        assertThat(session.expiresAt()).isEqualTo(expiresAt);
    }
}
