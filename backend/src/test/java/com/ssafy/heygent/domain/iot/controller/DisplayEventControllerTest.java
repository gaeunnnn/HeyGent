package com.ssafy.heygent.domain.iot.controller;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayEventType;
import com.ssafy.heygent.domain.iot.dto.DisplayIcon;
import com.ssafy.heygent.domain.iot.dto.DisplayPublishResult;
import com.ssafy.heygent.domain.iot.dto.StepRunDisplayPublishRequest;
import com.ssafy.heygent.domain.iot.service.DisplayEventPublishService;
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

@WebMvcTest(DisplayEventController.class)
@Import({SecurityConfig.class, JwtAuthenticationFilter.class, AiInternalAuthenticationFilter.class})
class DisplayEventControllerTest {

    private static final Long USER_ID = 1L;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private DisplayEventPublishService displayEventPublishService;

    @MockBean
    private JwtProvider jwtProvider;

    @MockBean
    private AiInternalProperties aiInternalProperties;

    @MockBean
    private JpaMetamodelMappingContext jpaMetamodelMappingContext;

    @Test
    void publishStepRunEventRequiresAuthentication() throws Exception {
        mockMvc.perform(post("/api/v1/iot/display/events")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request())))
            .andExpect(status().is4xxClientError());
    }

    @Test
    void publishStepRunEventCallsServiceWithAuthenticatedUser() throws Exception {
        DisplayEventPayload payload = new DisplayEventPayload(
            DisplayEventType.STEP,
            "session_test_001",
            "step_test_001",
            DisplayIcon.SEARCH,
            "searching",
            3000L,
            12L
        );
        DisplayPublishResult response = DisplayPublishResult.published(
            "devices/heygent-c3-a1b2c3/display",
            0,
            payload
        );
        when(displayEventPublishService.publish(
            eq(USER_ID),
            eq(DisplayEventType.STEP),
            eq(DisplayIcon.SEARCH),
            eq("session_test_001"),
            eq("step_test_001"),
            eq("searching")
        )).thenReturn(response);

        mockMvc.perform(post("/api/v1/iot/display/events")
                .with(user(new CustomUserPrincipal(USER_ID)))
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request())))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.data.published").value(true))
            .andExpect(jsonPath("$.data.topic").value("devices/heygent-c3-a1b2c3/display"));

        verify(displayEventPublishService).publish(
            eq(USER_ID),
            eq(DisplayEventType.STEP),
            eq(DisplayIcon.SEARCH),
            eq("session_test_001"),
            eq("step_test_001"),
            eq("searching")
        );
    }

    private StepRunDisplayPublishRequest request() {
        return new StepRunDisplayPublishRequest(
            DisplayEventType.STEP,
            DisplayIcon.SEARCH,
            "session_test_001",
            "step_test_001",
            "searching"
        );
    }
}
