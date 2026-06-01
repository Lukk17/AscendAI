package com.lukk.ascend.ai.agent.service.cache;

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
