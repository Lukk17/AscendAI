package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.Map;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.embedding")
public class EmbeddingProviderProperties {

    private static final String COLLECTION_PREFIX = "ascendai-";

    private String defaultProvider;
    private Map<String, EmbeddingConfig> providers;

    public EmbeddingConfig getActiveProvider() {
        return providers.get(defaultProvider);
    }

    public int getActiveDimensions() {
        return getActiveProvider().getDimensions();
    }

    public String getActiveCollectionName() {
        return COLLECTION_PREFIX + getActiveDimensions();
    }

    @Getter
    @Setter
    public static class EmbeddingConfig {
        private String type;
        private String baseUrl;
        private String apiKey;
        private String model;
        private int dimensions;
    }
}
