package com.lukk.ascend.ai.agent.service;

import org.springframework.util.StringUtils;

/**
 * Static + dynamic split of the assembled system prompt.
 *
 * <p>The {@code staticPrefix} is the {@code app.system-prompt} text only — globally
 * identical across users and turns, eligible for provider prompt caching. The
 * {@code dynamicSuffix} carries per-user content (instructions, semantic memory) that
 * varies per request and must NOT be marked as cacheable.
 */
public record AssembledSystemMessages(String staticPrefix, String dynamicSuffix) {

    public boolean hasDynamic() {
        return StringUtils.hasText(dynamicSuffix);
    }

    public String combined() {
        return hasDynamic() ? staticPrefix + "\n\n" + dynamicSuffix : staticPrefix;
    }
}
