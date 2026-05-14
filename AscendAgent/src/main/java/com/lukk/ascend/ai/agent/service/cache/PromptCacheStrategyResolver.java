package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.config.properties.PromptCacheProperties;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;
import java.util.Set;

@Service
@Slf4j
public class PromptCacheStrategyResolver {

    private static final String ANTHROPIC = "anthropic";
    private static final Set<String> OPENAI_FAMILY = Set.of("openai", "gemini");

    private final PromptCacheProperties properties;
    private final Map<String, PromptCacheStrategy> strategies = new HashMap<>();
    private final Map<String, PromptCacheStrategy> noopByProvider = new HashMap<>();

    public PromptCacheStrategyResolver(PromptCacheProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    void init() {
        strategies.put(ANTHROPIC, new AnthropicPromptCacheStrategy());
        for (String name : OPENAI_FAMILY) {
            strategies.put(name, new OpenAiPromptCacheStrategy(name));
        }
        log.info("[PromptCache] master enabled={}, provider toggles={}",
                properties.isEnabled(), properties.getProviders());
    }

    public PromptCacheStrategy resolve(String providerName) {
        if (providerName == null || !properties.isProviderEnabled(providerName)) {
            return noop(providerName);
        }
        PromptCacheStrategy s = strategies.get(providerName);
        return s != null ? s : noop(providerName);
    }

    private PromptCacheStrategy noop(String providerName) {
        return noopByProvider.computeIfAbsent(
                providerName == null ? "unknown" : providerName,
                NoopPromptCacheStrategy::new);
    }
}
