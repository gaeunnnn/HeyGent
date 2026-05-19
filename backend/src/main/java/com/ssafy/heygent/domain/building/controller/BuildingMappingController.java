package com.ssafy.heygent.domain.building.controller;

import com.ssafy.heygent.domain.building.dto.request.AssignFloorRequest;
import com.ssafy.heygent.domain.building.dto.response.BuildingMappingResponse;
import com.ssafy.heygent.domain.building.service.BuildingMappingService;
import com.ssafy.heygent.global.config.security.CustomUserPrincipal;
import com.ssafy.heygent.global.exception.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Tag(name = "Building", description = "건물 페이지의 층 ↔ AI 세션 매핑 API")
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/building/mappings")
public class BuildingMappingController {

    private final BuildingMappingService service;

    @Operation(summary = "내 층 매핑 전체 조회")
    @GetMapping
    public ApiResponse<List<BuildingMappingResponse>> listMyMappings(
            @AuthenticationPrincipal CustomUserPrincipal user
    ) {
        return ApiResponse.success(service.listMyMappings(user.getUserId()));
    }

    @Operation(summary = "특정 층에 세션 매핑(생성 또는 갱신)")
    @PutMapping("/{floor}")
    public ApiResponse<BuildingMappingResponse> assignFloor(
            @AuthenticationPrincipal CustomUserPrincipal user,
            @PathVariable Integer floor,
            @Valid @RequestBody AssignFloorRequest request
    ) {
        BuildingMappingResponse result = service.assignFloor(user.getUserId(), floor, request.getSessionId());
        return ApiResponse.success(result);
    }

    @Operation(summary = "특정 층 매핑 해제")
    @DeleteMapping("/{floor}")
    public ApiResponse<Void> clearFloor(
            @AuthenticationPrincipal CustomUserPrincipal user,
            @PathVariable Integer floor
    ) {
        service.clearFloor(user.getUserId(), floor);
        return ApiResponse.success(null);
    }
}
