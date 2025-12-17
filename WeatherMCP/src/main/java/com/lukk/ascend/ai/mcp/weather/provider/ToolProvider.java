package com.lukk.ascend.ai.mcp.weather.provider;

import com.lukk.ascend.ai.mcp.weather.service.WeatherToolService;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ToolProvider {

    @Bean
    public ToolCallbackProvider weatherTools(WeatherToolService weatherService) {
        return MethodToolCallbackProvider.builder().toolObjects(weatherService).build();
    }
}
