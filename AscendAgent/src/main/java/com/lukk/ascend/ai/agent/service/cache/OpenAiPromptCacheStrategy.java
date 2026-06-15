package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.util.StringUtils;

@Slf4j
public class OpenAiPromptCacheStrategy implements PromptCacheStrategy {

    private static final String METRIC_TOKENS_READ = "prompt_cache.tokens.read";
    private static final String METRIC_TOKENS_TOTAL = "prompt_cache.tokens.total";

    private final String providerName;
    private final MeterRegistry meterRegistry;

    public OpenAiPromptCacheStrategy(String providerName, MeterRegistry meterRegistry) {
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
        if (response == null) {
            return;
        }

        Usage usage = response.getMetadata().getUsage();
        if (usage == null) {
            return;
        }

        Integer cached = extractCachedTokens(usage.getNativeUsage());
        if (cached == null) {
            return;
        }

        int prompt = usage.getPromptTokens() != null ? usage.getPromptTokens() : 0;
        boolean hit = cached > 0;

        log.info("[PromptCache] provider={} user={} hit={} cached_tokens={} prompt_tokens={}",
                providerName, userId, hit, cached, prompt);

        Counter.builder(METRIC_TOKENS_READ).tag("provider", providerName).register(meterRegistry).increment(cached);
        Counter.builder(METRIC_TOKENS_TOTAL).tag("provider", providerName).register(meterRegistry).increment(prompt);
    }

    private static Integer extractCachedTokens(Object nativeUsage) {
        if (nativeUsage instanceof OpenAiApi.Usage oai) {
            OpenAiApi.Usage.PromptTokensDetails details = oai.promptTokensDetails();

            return details == null ? null : details.cachedTokens();
        }

        return null;
    }
}
