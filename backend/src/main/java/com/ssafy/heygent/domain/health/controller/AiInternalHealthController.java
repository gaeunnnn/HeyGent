package com.ssafy.heygent.domain.health.controller;

import java.util.List;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.ssafy.heygent.domain.health.dto.request.HealthExecuteRequest;
import com.ssafy.heygent.domain.health.dto.response.HealthExecuteCommandResponse;
import com.ssafy.heygent.domain.health.service.HealthService;
import com.ssafy.heygent.global.exception.ApiResponse;

import io.swagger.v3.oas.annotations.Operation;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;

@RestController
@RequiredArgsConstructor
@RequestMapping("/internal/ai/health")
public class AiInternalHealthController {

    private final HealthService healthService;

    @Operation(summary = "AI 내부 Health 명령 배치 실행", description = "AI 서버가 내부 인증 토큰과 userId로 Health 조회 명령을 실행합니다.")
    @PostMapping("/execute")
    public ApiResponse<List<HealthExecuteCommandResponse>> execute(
        @Valid @RequestBody HealthExecuteRequest request
    ) {
        return ApiResponse.success(healthService.executeBatch(
            request.getUserId(),
            request.getCommands()
        ));
    }
}
