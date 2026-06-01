package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.memory.semantic")
public class SemanticMemoryProperties {

    private boolean enabled = true;

    private String baseUrl = "http://localhost:7020";

    private int searchLimit = 5;
}
