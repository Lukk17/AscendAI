package com.lukk.ascend.ai.agent.memory;

import org.springframework.util.StringUtils;

public record CompactionOverride(String provider, String model) {

    public static final CompactionOverride EMPTY = new CompactionOverride(null, null);

    public boolean hasProvider() {
        return StringUtils.hasText(provider);
    }

    public boolean hasModel() {
        return StringUtils.hasText(model);
    }
}
