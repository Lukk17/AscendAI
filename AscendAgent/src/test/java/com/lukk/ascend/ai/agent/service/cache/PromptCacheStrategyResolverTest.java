package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.config.properties.PromptCacheProperties;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class PromptCacheStrategyResolverTest {

    @Test
    void resolve_AnthropicWhenEnabled_ReturnsAnthropicStrategy() {
        PromptCacheStrategyResolver resolver = build(true, Map.of("anthropic", true));
        PromptCacheStrategy s = resolver.resolve("anthropic");
        assertThat(s).isInstanceOf(AnthropicPromptCacheStrategy.class);
        assertThat(s.providerName()).isEqualTo("anthropic");
    }

    @Test
    void resolve_OpenAiAndGeminiWhenEnabled_ReturnsOpenAiStrategy() {
        PromptCacheStrategyResolver resolver = build(true, Map.of("openai", true, "gemini", true));
        assertThat(resolver.resolve("openai")).isInstanceOf(OpenAiPromptCacheStrategy.class);
        assertThat(resolver.resolve("gemini")).isInstanceOf(OpenAiPromptCacheStrategy.class);
    }

    @Test
    void resolve_LmstudioOrMinimax_AlwaysNoop() {
        PromptCacheStrategyResolver resolver = build(true, Map.of("lmstudio", true, "minimax", true));
        assertThat(resolver.resolve("lmstudio")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve("minimax")).isInstanceOf(NoopPromptCacheStrategy.class);
    }

    @Test
    void resolve_MasterToggleOff_AlwaysNoop() {
        PromptCacheStrategyResolver resolver = build(false, Map.of("anthropic", true));
        assertThat(resolver.resolve("anthropic")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve("openai")).isInstanceOf(NoopPromptCacheStrategy.class);
    }

    @Test
    void resolve_PerProviderToggleOff_OnlyThatProviderNoop() {
        PromptCacheStrategyResolver resolver = build(true, Map.of("anthropic", false, "openai", true));
        assertThat(resolver.resolve("anthropic")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve("openai")).isInstanceOf(OpenAiPromptCacheStrategy.class);
    }

    @Test
    void resolve_UnknownProvider_ReturnsNoop() {
        PromptCacheStrategyResolver resolver = build(true, Map.of());
        assertThat(resolver.resolve("doesnotexist")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve(null)).isInstanceOf(NoopPromptCacheStrategy.class);
    }

    @Test
    void resolve_NoopReusedAcrossCallsForSameProvider() {
        PromptCacheStrategyResolver resolver = build(true, Map.of());
        PromptCacheStrategy a = resolver.resolve("foo");
        PromptCacheStrategy b = resolver.resolve("foo");
        assertThat(a).isSameAs(b);
    }

    private PromptCacheStrategyResolver build(boolean masterEnabled, Map<String, Boolean> perProvider) {
        PromptCacheProperties props = new PromptCacheProperties();
        props.setEnabled(masterEnabled);
        Map<String, PromptCacheProperties.ProviderCache> map = new java.util.HashMap<>();
        perProvider.forEach((k, v) -> {
            PromptCacheProperties.ProviderCache pc = new PromptCacheProperties.ProviderCache();
            pc.setEnabled(v);
            map.put(k, pc);
        });
        props.setProviders(map);
        PromptCacheStrategyResolver resolver = new PromptCacheStrategyResolver(props);
        resolver.init();
        return resolver;
    }
}
