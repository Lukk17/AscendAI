package com.lukk.ascend.ai.agent.config.mcp;

import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers a no-op {@link ToolCallbackProvider} when no other provider is active.
 *
 * <p>When {@code spring.ai.mcp.client.enabled=false} the {@link FilteredToolCallbackProvider}
 * is not created (see ADR-008). {@link com.lukk.ascend.ai.agent.service.chat.ChatExecutor}
 * requires a {@link ToolCallbackProvider} bean, so without this fallback the context fails
 * to start. The fallback simply returns an empty callback array, making the application
 * start cleanly with no tools registered.
 */
@Configuration
public class FallbackToolCallbackProvider {

    @Bean
    @ConditionalOnMissingBean(ToolCallbackProvider.class)
    ToolCallbackProvider noOpToolCallbackProvider() {
        return () -> new ToolCallback[0];
    }
}
