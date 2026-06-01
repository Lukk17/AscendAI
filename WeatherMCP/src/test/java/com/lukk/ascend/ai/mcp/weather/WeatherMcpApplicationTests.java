package com.lukk.ascend.ai.mcp.weather;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;

import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class WeatherMcpApplicationTests {

    private static final List<String> EXPECTED_TOOL_NAMES = List.of(
            "weather.current",
            "weather.forecast",
            "weather.historical",
            "weather.airQuality",
            "weather.geocode"
    );

    @Autowired
    private ApplicationContext applicationContext;

    @Autowired
    private ToolCallbackProvider toolCallbackProvider;

    @Test
    @DisplayName("Spring context loads successfully")
    void contextLoads() {
        // then
        assertThat(applicationContext).isNotNull();
    }

    @Test
    @DisplayName("ToolCallbackProvider publishes exactly the five expected weather tools")
    void toolCallbackProvider_PublishesWeatherTools() {
        // given
        ToolCallback[] tools = toolCallbackProvider.getToolCallbacks();
        List<String> publishedNames = Arrays.stream(tools)
                .map(t -> t.getToolDefinition().name())
                .toList();

        // then
        assertThat(publishedNames).containsExactlyInAnyOrderElementsOf(EXPECTED_TOOL_NAMES);
    }
}
