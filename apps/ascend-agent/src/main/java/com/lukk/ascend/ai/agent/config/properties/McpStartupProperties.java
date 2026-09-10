package com.lukk.ascend.ai.agent.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@ConfigurationProperties(prefix = "app.mcp.startup")
public class McpStartupProperties {

    private Duration initTimeout = Duration.ofSeconds(5);

    public Duration getInitTimeout() {
        return initTimeout;
    }

    public void setInitTimeout(Duration initTimeout) {
        this.initTimeout = initTimeout;
    }
}
