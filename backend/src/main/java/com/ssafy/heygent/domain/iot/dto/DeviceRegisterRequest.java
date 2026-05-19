package com.ssafy.heygent.domain.iot.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record DeviceRegisterRequest(
    @NotBlank @Size(max = 80) @Pattern(regexp = "heygent-c3-[0-9a-fA-F]{6}") String deviceId,
    @Size(max = 100) String displayName
) {
}
