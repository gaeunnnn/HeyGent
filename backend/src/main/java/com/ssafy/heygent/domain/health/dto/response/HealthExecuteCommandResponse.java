package com.ssafy.heygent.domain.health.dto.response;

import lombok.Getter;

@Getter
public class HealthExecuteCommandResponse {

    private final int index;
    private final Long userId;
    private final String method;
    private final String endpoint;
    private final boolean success;
    private final Object data;
    private final String errorCode;
    private final String errorMessage;

    private HealthExecuteCommandResponse(
        int index,
        Long userId,
        String method,
        String endpoint,
        boolean success,
        Object data,
        String errorCode,
        String errorMessage
    ) {
        this.index = index;
        this.userId = userId;
        this.method = method;
        this.endpoint = endpoint;
        this.success = success;
        this.data = data;
        this.errorCode = errorCode;
        this.errorMessage = errorMessage;
    }

    public static HealthExecuteCommandResponse success(
        int index,
        Long userId,
        String method,
        String endpoint,
        Object data
    ) {
        return new HealthExecuteCommandResponse(
            index,
            userId,
            method,
            endpoint,
            true,
            data,
            null,
            null
        );
    }

    public static HealthExecuteCommandResponse failure(
        int index,
        Long userId,
        String method,
        String endpoint,
        String errorCode,
        String errorMessage
    ) {
        return new HealthExecuteCommandResponse(
            index,
            userId,
            method,
            endpoint,
            false,
            null,
            errorCode,
            errorMessage
        );
    }
}
