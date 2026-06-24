package com.lukk.ascend.ai.agent.config;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.binder.MeterBinder;
import org.springframework.boot.actuate.autoconfigure.metrics.MeterRegistryCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MetricsConfig {

    @Bean
    MeterRegistryCustomizer<MeterRegistry> commonTags() {
        return registry -> registry.config()
                .commonTags("service", "ascend-agent");
    }

    @Bean
    MeterBinder chatHistorySizeGaugeStub() {
        return registry -> Gauge.builder("chat.history.size", () -> 0.0)
                .description("Number of messages in the active chat history (stub; default 0 until real tracking is wired)")
                .register(registry);
    }
}
