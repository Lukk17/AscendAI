package com.lukk.ascend.ai.agent.config.mcp;

import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers a no-op {@link ToolCallbackProvider} when the MCP client is switched off.
 *
 * <p>The condition mirrors {@link FilteredToolCallbackProvider}, so exactly one of the two
 * is ever present and {@code ChatExecutor} always finds the provider it requires.
 */
@Configuration
@ConditionalOnProperty(prefix = "spring.ai.mcp.client", name = "enabled", havingValue = "false")
public class FallbackToolCallbackProvider {

    @Bean
    ToolCallbackProvider noOpToolCallbackProvider() {
        return () -> new ToolCallback[0];
    }
}
