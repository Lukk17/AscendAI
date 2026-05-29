package com.lukk.ascend.ai.agent.service.cache;

import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.util.StringUtils;

public record NoopPromptCacheStrategy(String providerName) implements PromptCacheStrategy {

    @Override
    public ChatOptions buildOptions(String model) {
        return StringUtils.hasText(model) ? ChatOptions.builder().model(model).build() : null;
    }

    @Override
    public void recordOutcome(String userId, ChatResponse response) {
    }
}
