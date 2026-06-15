package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.anthropic.AnthropicChatOptions;
import org.springframework.ai.anthropic.api.AnthropicApi;
import org.springframework.ai.anthropic.api.AnthropicCacheOptions;
import org.springframework.ai.anthropic.api.AnthropicCacheStrategy;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.util.StringUtils;

@Slf4j
public class AnthropicPromptCacheStrategy implements PromptCacheStrategy {

    private static final String PROVIDER = "anthropic";
    private static final String METRIC_TOKENS_READ = "prompt_cache.tokens.read";
    private static final String METRIC_TOKENS_CREATION = "prompt_cache.tokens.creation";
    private static final String METRIC_TOKENS_TOTAL = "prompt_cache.tokens.total";

    private final MeterRegistry meterRegistry;

    public AnthropicPromptCacheStrategy(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    @Override
    public String providerName() {
        return PROVIDER;
    }

    @Override
    public ChatOptions buildOptions(String model) {
        AnthropicCacheOptions cache = AnthropicCacheOptions.builder()
                .strategy(AnthropicCacheStrategy.SYSTEM_ONLY)
                .multiBlockSystemCaching(true)
                .build();

        AnthropicChatOptions.Builder builder = AnthropicChatOptions.builder()
                .cacheOptions(cache);
        if (StringUtils.hasText(model)) {
            builder.model(model);
        }
        return builder.build();
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

        if (!(usage.getNativeUsage() instanceof AnthropicApi.Usage anth)) {
            return;
        }

        Integer read = anth.cacheReadInputTokens();
        Integer creation = anth.cacheCreationInputTokens();
        int prompt = usage.getPromptTokens() != null ? usage.getPromptTokens() : 0;
        boolean hit = read != null && read > 0;

        log.info("[PromptCache] provider={} user={} hit={} cache_read_tokens={} cache_creation_tokens={} prompt_tokens={}",
                PROVIDER, userId, hit, nullToZero(read), nullToZero(creation), prompt);

        Counter.builder(METRIC_TOKENS_READ).tag("provider", PROVIDER).register(meterRegistry).increment(nullToZero(read));
        Counter.builder(METRIC_TOKENS_CREATION).tag("provider", PROVIDER).register(meterRegistry).increment(nullToZero(creation));
        Counter.builder(METRIC_TOKENS_TOTAL).tag("provider", PROVIDER).register(meterRegistry).increment(prompt);
    }

    @Override
    public boolean isCacheConfigError(Throwable t) {
        if (t == null) {
            return false;
        }
        String msg = t.getMessage();
        if (msg == null) {
            return false;
        }
        String lower = msg.toLowerCase();
        return lower.contains("cache_control") || lower.contains("cache-control")
                || (lower.contains("400") && lower.contains("cache"));
    }

    private static int nullToZero(Integer v) {
        return v == null ? 0 : v;
    }
}
