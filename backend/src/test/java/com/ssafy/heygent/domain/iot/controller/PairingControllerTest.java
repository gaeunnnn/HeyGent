package com.ssafy.heygent.domain.iot.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.heygent.domain.iot.dto.DevicePairingStatusResponse;
import com.ssafy.heygent.domain.iot.dto.DisplayPairingStartRequest;
import com.ssafy.heygent.domain.iot.dto.DisplayPairingStartResponse;
import com.ssafy.heygent.domain.iot.service.DevicePairingService;
import com.ssafy.heygent.global.config.jwt.JwtProvider;
import com.ssafy.heygent.global.config.security.AiInternalAuthenticationFilter;
import com.ssafy.heygent.global.config.security.AiInternalProperties;
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

@WebMvcTest(PairingController.class)
@Import({SecurityConfig.class, JwtAuthenticationFilter.class, AiInternalAuthenticationFilter.class})
class PairingControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private DevicePairingService devicePairingService;

    @MockBean
    private JwtProvider jwtProvider;

    @MockBean
    private AiInternalProperties aiInternalProperties;

    @MockBean
    private JpaMetamodelMappingContext jpaMetamodelMappingContext;

    @Test
    void startIsAllowedWithoutAuthentication() throws Exception {
        when(devicePairingService.start(any(DisplayPairingStartRequest.class)))
            .thenReturn(new DisplayPairingStartResponse("482913", 300L));

        mockMvc.perform(post("/api/v1/iot/pairing/start")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new DisplayPairingStartRequest(
                    "heygent-c3-a1b2c3",
                    "nonce-001",
                    "0.1.0"
                ))))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data.pairCode").value("482913"))
            .andExpect(jsonPath("$.data.expiresInSeconds").value(300L));
    }

    @Test
    void statusIsAllowedWithoutAuthentication() throws Exception {
        when(devicePairingService.status("heygent-c3-a1b2c3"))
            .thenReturn(DevicePairingStatusResponse.unpaired("heygent-c3-a1b2c3"));

        mockMvc.perform(get("/api/v1/iot/pairing/devices/{deviceId}/status", "heygent-c3-a1b2c3"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data.deviceId").value("heygent-c3-a1b2c3"))
            .andExpect(jsonPath("$.data.paired").value(false))
            .andExpect(jsonPath("$.data.status").value("UNPAIRED"));
    }
}
