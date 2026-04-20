package com.lukk.ascend.ai.orchestrator.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.vectorstore")
public class VectorStoreProperties {

    private List<CollectionConfig> collections;

    @Getter
    @Setter
    public static class CollectionConfig {
        private String name;
        private int size;
    }
}
