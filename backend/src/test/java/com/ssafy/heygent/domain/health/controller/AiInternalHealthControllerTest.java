package com.ssafy.heygent.domain.health.controller;

import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.data.jpa.mapping.JpaMetamodelMappingContext;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.ssafy.heygent.domain.health.dto.response.HealthExecuteCommandResponse;
import com.ssafy.heygent.domain.health.service.HealthService;
import com.ssafy.heygent.global.config.jwt.JwtProvider;
import com.ssafy.heygent.global.config.security.AiInternalAuthenticationFilter;
import com.ssafy.heygent.global.config.security.AiInternalProperties;
import com.ssafy.heygent.global.config.security.JwtAuthenticationFilter;
import com.ssafy.heygent.global.config.security.SecurityConfig;

@WebMvcTest(AiInternalHealthController.class)
@Import({SecurityConfig.class, JwtAuthenticationFilter.class, AiInternalAuthenticationFilter.class})
class AiInternalHealthControllerTest {

    private static final String INTERNAL_TOKEN = "internal-test-token";
    private static final Long USER_ID = 1L;

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private HealthService healthService;

    @MockBean
    private JwtProvider jwtProvider;

    @MockBean
    private AiInternalProperties aiInternalProperties;

    @MockBean
    private JpaMetamodelMappingContext jpaMetamodelMappingContext;

    @BeforeEach
    void setUp() {
        when(aiInternalProperties.getToken()).thenReturn(INTERNAL_TOKEN);
    }

    @Test
    void executeRequiresInternalToken() throws Exception {
        mockMvc.perform(post("/internal/ai/health/execute")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {
                      "userId": 1,
                      "commands": [
                        {"method": "GET", "endpoint": "/api/v1/health/me/latest"}
                      ]
                    }
                    """))
            .andExpect(status().isUnauthorized());
    }

    @Test
    void executeCallsHealthServiceWithUserIdAndCommands() throws Exception {
        when(healthService.executeBatch(eq(USER_ID), anyList()))
            .thenReturn(List.of(HealthExecuteCommandResponse.success(
                0,
                USER_ID,
                "GET",
                "/api/v1/health/me/latest",
                null
            )));

        mockMvc.perform(post("/internal/ai/health/execute")
                .header("Authorization", "Bearer " + INTERNAL_TOKEN)
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {
                      "userId": 1,
                      "commands": [
                        {"method": "GET", "endpoint": "/api/v1/health/me/latest"}
                      ]
                    }
                    """))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data[0].success").value(true))
            .andExpect(jsonPath("$.data[0].endpoint").value("/api/v1/health/me/latest"));

        verify(healthService).executeBatch(eq(USER_ID), anyList());
    }
}
