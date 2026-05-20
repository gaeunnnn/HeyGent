package com.ssafy.heygent.domain.health.dto.request;

import java.util.Map;

import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor
public class HealthExecuteCommandRequest {

    @NotBlank
    private String method;

    @NotBlank
    private String endpoint;

    private Map<String, Object> params;
}
