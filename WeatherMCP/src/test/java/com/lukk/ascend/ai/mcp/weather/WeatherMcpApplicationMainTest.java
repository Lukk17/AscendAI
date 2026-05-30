package com.lukk.ascend.ai.mcp.weather;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.springframework.boot.SpringApplication;

import static org.mockito.Mockito.mockStatic;

class WeatherMcpApplicationMainTest {

    @Test
    @DisplayName("main forwards its arguments to SpringApplication.run with WeatherMcpApplication as the primary source")
    void main_forwardsArgsToSpringApplicationRun() {
        // given
        String[] args = {"--foo=bar", "--server.port=0"};

        // when
        try (MockedStatic<SpringApplication> mocked = mockStatic(SpringApplication.class)) {
            WeatherMcpApplication.main(args);

            // then
            mocked.verify(() -> SpringApplication.run(WeatherMcpApplication.class, args));
        }
    }
}
