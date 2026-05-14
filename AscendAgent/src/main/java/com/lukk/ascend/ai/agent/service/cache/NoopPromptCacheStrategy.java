package com.lukk.ascend.ai.agent.service.cache;

import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.util.StringUtils;

public class NoopPromptCacheStrategy implements PromptCacheStrategy {

    private final String providerName;

    public NoopPromptCacheStrategy(String providerName) {
        this.providerName = providerName;
    }

    @Override
    public String providerName() {
        return providerName;
    }

    @Override
    public ChatOptions buildOptions(String model) {
        return StringUtils.hasText(model) ? ChatOptions.builder().model(model).build() : null;
    }

    @Override
    public void recordOutcome(String userId, ChatResponse response) {
        // intentional no-op
    }
}
