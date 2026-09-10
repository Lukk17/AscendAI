package com.lukk.ascend.ai.mcp.weather.config;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.config.MeterFilter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MetricsConfig {

    @Bean
    io.micrometer.core.instrument.binder.MeterBinder commonTagsBinder() {
        return registry -> registry.config()
                .commonTags("service", "ascend-weather-mcp");
    }
}
