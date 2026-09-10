package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.util.StringUtils;

public final class NoopPromptCacheStrategy implements PromptCacheStrategy {

    private final String providerName;
    private final MeterRegistry meterRegistry;

    public NoopPromptCacheStrategy(String providerName, MeterRegistry meterRegistry) {
        this.providerName = providerName;
        this.meterRegistry = meterRegistry;
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
        GenAiTokenUsageRecorder.record(meterRegistry, response, providerName);
    }
}
