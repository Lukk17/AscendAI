package com.lukk.ascend.ai.agent.service.cache;

import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;

public interface PromptCacheStrategy {

    String providerName();

    // Returns null when the caller should fall back to its default options path.
    ChatOptions buildOptions(String model);

    void recordOutcome(String userId, ChatResponse response);

    // Returns false for non-cache exceptions, so the caller propagates them unchanged.
    // Returns true only for cache-config errors that should trigger one retry without cache decoration.
    default boolean isCacheConfigError(Throwable t) {
        return false;
    }
}
