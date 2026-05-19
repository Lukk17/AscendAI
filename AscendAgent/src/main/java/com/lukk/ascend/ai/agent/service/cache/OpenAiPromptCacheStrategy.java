package com.lukk.ascend.ai.agent.service.cache;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.util.StringUtils;

@Slf4j
public class OpenAiPromptCacheStrategy implements PromptCacheStrategy {

    private final String providerName;

    public OpenAiPromptCacheStrategy(String providerName) {
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
        if (response == null || response.getMetadata() == null) {
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
    }

    private static Integer extractCachedTokens(Object nativeUsage) {
        if (nativeUsage instanceof OpenAiApi.Usage oai) {
            OpenAiApi.Usage.PromptTokensDetails details = oai.promptTokensDetails();
            return details == null ? null : details.cachedTokens();
        }
        return null;
    }
}
