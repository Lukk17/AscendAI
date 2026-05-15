package com.lukk.ascend.ai.agent.memory;

import org.springframework.util.StringUtils;

/**
 * Per-request override for the chat-history compaction model.
 * Both fields are optional; null/blank means "use the default for the request's primary provider".
 */
public record CompactionOverride(String provider, String model) {

    public static final CompactionOverride EMPTY = new CompactionOverride(null, null);

    public boolean hasProvider() {
        return StringUtils.hasText(provider);
    }

    public boolean hasModel() {
        return StringUtils.hasText(model);
    }
}
