package com.lukk.ascend.ai.agent.service.cache;

import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;

public interface PromptCacheStrategy {

    String providerName();

    /**
     * Build provider-specific {@link ChatOptions} carrying cache directives. May return
     * {@code null} when the caller should fall back to its default options path.
     */
    ChatOptions buildOptions(String model);

    /**
     * Read cache-token counters from the response metadata and emit a single INFO log line.
     */
    void recordOutcome(String userId, ChatResponse response);

    /**
     * Whether the throwable is a cache-config error that should trigger exactly one
     * retry without cache decoration. Non-cache exceptions return {@code false} so the
     * caller propagates them unchanged.
     */
    default boolean isCacheConfigError(Throwable t) {
        return false;
    }
}
