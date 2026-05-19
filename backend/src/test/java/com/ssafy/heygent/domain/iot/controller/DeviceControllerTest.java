package com.ssafy.heygent.domain.iot.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.heygent.domain.iot.dto.DevicePairRequest;
import com.ssafy.heygent.domain.iot.dto.DeviceResponse;
import com.ssafy.heygent.domain.iot.entity.IotDeviceStatus;
import com.ssafy.heygent.domain.iot.service.DeviceDisplayCoordinator;
import com.ssafy.heygent.domain.iot.service.DevicePairingService;
import com.ssafy.heygent.domain.iot.service.DeviceService;
import com.ssafy.heygent.global.config.jwt.JwtProvider;
import com.ssafy.heygent.global.config.security.AiInternalAuthenticationFilter;
import com.ssafy.heygent.global.config.security.AiInternalProperties;
import com.ssafy.heygent.global.config.security.CustomUserPrincipal;
import com.ssafy.heygent.global.config.security.JwtAuthenticationFilter;
import com.ssafy.heygent.global.config.security.SecurityConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.data.jpa.mapping.JpaMetamodelMappingContext;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;

@WebMvcTest(DeviceController.class)
@Import({SecurityConfig.class, JwtAuthenticationFilter.class, AiInternalAuthenticationFilter.class})
class DeviceControllerTest {

    private static final Long USER_ID = 1L;
    private static final String DEVICE_ID = "heygent-c3-a1b2c3";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private DeviceService deviceService;

    @MockBean
    private DevicePairingService devicePairingService;

    @MockBean
    private DeviceDisplayCoordinator deviceDisplayCoordinator;

    @MockBean
    private JwtProvider jwtProvider;

    @MockBean
    private AiInternalProperties aiInternalProperties;

    @MockBean
    private JpaMetamodelMappingContext jpaMetamodelMappingContext;

    @Test
    void pairRequiresAuthentication() throws Exception {
        mockMvc.perform(post("/api/v1/iot/devices/pair")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new DevicePairRequest("482913", "desk oled"))))
            .andExpect(status().is4xxClientError());
    }

    @Test
    void pairCallsServiceWithAuthenticatedUser() throws Exception {
        DeviceResponse response = new DeviceResponse(
            10L,
            DEVICE_ID,
            "desk oled",
            IotDeviceStatus.ACTIVE,
            null,
            LocalDateTime.of(2026, 5, 5, 20, 0),
            LocalDateTime.of(2026, 5, 5, 20, 0)
        );
        when(devicePairingService.pair(eq(USER_ID), any(DevicePairRequest.class))).thenReturn(response);

        mockMvc.perform(post("/api/v1/iot/devices/pair")
                .with(user(new CustomUserPrincipal(USER_ID)))
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new DevicePairRequest("482913", "desk oled"))))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data.deviceId").value(DEVICE_ID));

        verify(devicePairingService).pair(eq(USER_ID), any(DevicePairRequest.class));
    }

    @Test
    void unpairRequiresAuthentication() throws Exception {
        mockMvc.perform(delete("/api/v1/iot/devices/{deviceId}", DEVICE_ID))
            .andExpect(status().is4xxClientError());
    }

    @Test
    void unpairCallsServiceWithAuthenticatedUser() throws Exception {
        mockMvc.perform(delete("/api/v1/iot/devices/{deviceId}", DEVICE_ID)
                .with(user(new CustomUserPrincipal(USER_ID))))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data").doesNotExist());

        verify(deviceService).unpair(USER_ID, DEVICE_ID);
    }
}
