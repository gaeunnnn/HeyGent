package com.ssafy.heygent.domain.mattermost.service;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class MattermostServiceTest {

    private static final String HEADER = "# :ai: HeyGent에서 온 메시지 입니다 :ai:";

    @Test
    void withHeygentHeaderAddsHeader() {
        String message = MattermostService.withHeygentHeader("테스트 메시지");

        assertThat(message).isEqualTo(HEADER + "\n\n테스트 메시지");
    }

    @Test
    void withHeygentHeaderDoesNotDuplicateHeader() {
        String original = HEADER + "\n\n이미 헤더가 있는 메시지";

        String message = MattermostService.withHeygentHeader(original);

        assertThat(message).isEqualTo(original);
    }
}
