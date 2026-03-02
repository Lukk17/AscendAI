package com.lukk.ascend.ai.orchestrator.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.Map;

@ConfigurationProperties(prefix = "app.ai")
@Getter
@Setter
public class AiProviderProperties {

    private String defaultProvider;
    private Map<String, ProviderConfig> providers = new LinkedHashMap<>();

    @Getter
    @Setter
    public static class ProviderConfig {
        private boolean enabled;
        private String type;
        private String baseUrl;
        private String apiKey;
        private String model;
        private double temperature;
    }
}
