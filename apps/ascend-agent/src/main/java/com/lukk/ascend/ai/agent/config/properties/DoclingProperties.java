package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.docling")
public class DoclingProperties {

    private int retryAttempts = 2;

    private Duration retryDelay = Duration.ofMillis(500);
}
