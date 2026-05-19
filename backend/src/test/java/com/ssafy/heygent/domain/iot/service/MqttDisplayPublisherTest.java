package com.ssafy.heygent.domain.iot.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.heygent.domain.iot.config.MqttProperties;
import com.ssafy.heygent.domain.iot.dto.DisplayEventPayload;
import com.ssafy.heygent.domain.iot.dto.DisplayEventType;
import com.ssafy.heygent.domain.iot.dto.DisplayIcon;
import com.ssafy.heygent.domain.iot.dto.DisplayPublishResult;
import com.ssafy.heygent.domain.iot.gateway.MqttDisplayGateway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.beans.factory.ObjectProvider;

@ExtendWith(MockitoExtension.class)
class MqttDisplayPublisherTest {

    private static final String DEVICE_ID = "heygent-c3-a1b2c3";

    @Mock
    private ObjectProvider<MqttDisplayGateway> gatewayProvider;

    @Mock
    private MqttDisplayGateway gateway;

    private MqttProperties properties;
    private ObjectMapper objectMapper;
    private MqttDisplayPublisher publisher;

    @BeforeEach
    void setUp() {
        properties = new MqttProperties();
        objectMapper = new ObjectMapper();
        publisher = new MqttDisplayPublisher(properties, gatewayProvider, objectMapper);
    }

    @Test
    void publishSkipsWhenMqttIsDisabled() {
        DisplayEventPayload payload = payload(DisplayEventType.STEP, DisplayIcon.SEARCH);

        DisplayPublishResult result = publisher.publish(DEVICE_ID, payload);

        assertThat(result.published()).isFalse();
        assertThat(result.topic()).isEqualTo("devices/heygent-c3-a1b2c3/display");
        assertThat(result.qos()).isZero();
        assertThat(result.reason()).isEqualTo("MQTT disabled");
        verify(gatewayProvider, never()).getIfAvailable();
    }

    @Test
    void publishSkipsWhenGatewayIsUnavailable() {
        properties.setEnabled(true);
        when(gatewayProvider.getIfAvailable()).thenReturn(null);
        DisplayEventPayload payload = payload(DisplayEventType.STEP, DisplayIcon.SEARCH);

        DisplayPublishResult result = publisher.publish(DEVICE_ID, payload);

        assertThat(result.published()).isFalse();
        assertThat(result.topic()).isEqualTo("devices/heygent-c3-a1b2c3/display");
        assertThat(result.qos()).isZero();
        assertThat(result.reason()).isEqualTo("MQTT gateway unavailable");
    }

    @Test
    void publishUsesDefaultQosForStepAndSendsJsonPayload() throws Exception {
        properties.setEnabled(true);
        properties.setDefaultQos(0);
        when(gatewayProvider.getIfAvailable()).thenReturn(gateway);
        DisplayEventPayload payload = payload(DisplayEventType.STEP, DisplayIcon.SEARCH);

        DisplayPublishResult result = publisher.publish(DEVICE_ID, payload);

        assertThat(result.published()).isTrue();
        assertThat(result.topic()).isEqualTo("devices/heygent-c3-a1b2c3/display");
        assertThat(result.qos()).isZero();

        ArgumentCaptor<String> topicCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> payloadCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Integer> qosCaptor = ArgumentCaptor.forClass(Integer.class);
        verify(gateway).publish(topicCaptor.capture(), payloadCaptor.capture(), qosCaptor.capture());

        JsonNode json = objectMapper.readTree(payloadCaptor.getValue());
        assertThat(topicCaptor.getValue()).isEqualTo("devices/heygent-c3-a1b2c3/display");
        assertThat(qosCaptor.getValue()).isZero();
        assertThat(json.get("type").asText()).isEqualTo("STEP");
        assertThat(json.get("icon").asText()).isEqualTo("search");
        assertThat(json.get("sessionId").asText()).isEqualTo("session_test_001");
        assertThat(json.get("stepRunId").asText()).isEqualTo("step_test_001");
        assertThat(json.get("text").asText()).isEqualTo("searching");
        assertThat(json.get("ttlMs").asLong()).isEqualTo(3000L);
        assertThat(json.get("seq").asLong()).isEqualTo(12L);
    }

    @Test
    void publishUsesQosOneForWaitingAndCanceled() {
        properties.setEnabled(true);
        when(gatewayProvider.getIfAvailable()).thenReturn(gateway);

        DisplayPublishResult waitingResult = publisher.publish(DEVICE_ID, payload(DisplayEventType.WAITING, DisplayIcon.WAIT));
        DisplayPublishResult canceledResult = publisher.publish(DEVICE_ID, payload(DisplayEventType.CANCELED, DisplayIcon.CANCEL));

        assertThat(waitingResult.qos()).isEqualTo(1);
        assertThat(canceledResult.qos()).isEqualTo(1);
        verify(gateway).publish("devices/heygent-c3-a1b2c3/display", jsonFor(DisplayEventType.WAITING, DisplayIcon.WAIT), 1);
        verify(gateway).publish("devices/heygent-c3-a1b2c3/display", jsonFor(DisplayEventType.CANCELED, DisplayIcon.CANCEL), 1);
    }

    @Test
    void publishBuildsTopicFromConfiguredPrefix() {
        properties.setEnabled(true);
        properties.setTopicPrefix("/devices/local/");
        when(gatewayProvider.getIfAvailable()).thenReturn(gateway);

        DisplayPublishResult result = publisher.publish("/" + DEVICE_ID + "/", payload(DisplayEventType.INFO, DisplayIcon.INFO));

        assertThat(result.topic()).isEqualTo("devices/local/heygent-c3-a1b2c3/display");
    }

    private DisplayEventPayload payload(DisplayEventType type, DisplayIcon icon) {
        return new DisplayEventPayload(
            type,
            "session_test_001",
            "step_test_001",
            icon,
            "searching",
            3000L,
            12L
        );
    }

    private String jsonFor(DisplayEventType type, DisplayIcon icon) {
        try {
            return objectMapper.writeValueAsString(payload(type, icon));
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }
}
