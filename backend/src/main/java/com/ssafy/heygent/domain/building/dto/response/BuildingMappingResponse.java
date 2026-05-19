package com.ssafy.heygent.domain.building.dto.response;

import com.ssafy.heygent.domain.building.entity.BuildingMapping;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
@AllArgsConstructor
public class BuildingMappingResponse {

    private Integer floor;
    private String sessionId;

    public static BuildingMappingResponse from(BuildingMapping mapping) {
        return BuildingMappingResponse.builder()
                .floor(mapping.getFloor())
                .sessionId(mapping.getSessionId())
                .build();
    }
}
