package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@Getter
@Setter
@ConfigurationProperties(prefix = "app.mcp.tool-cache")
public class McpToolCacheProperties {

    private Duration ttl = Duration.ofSeconds(60);
}
