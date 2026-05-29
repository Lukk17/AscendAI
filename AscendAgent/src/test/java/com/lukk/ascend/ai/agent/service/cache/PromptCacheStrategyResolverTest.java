package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.config.properties.PromptCacheProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class PromptCacheStrategyResolverTest {

    @Test
    @DisplayName("resolve returns AnthropicPromptCacheStrategy for anthropic when cache is enabled")
    void resolve_AnthropicWhenEnabled_ReturnsAnthropicStrategy() {
        // given
        PromptCacheStrategyResolver resolver = build(true, Map.of("anthropic", true));

        // when
        PromptCacheStrategy s = resolver.resolve("anthropic");

        // then
        assertThat(s).isInstanceOf(AnthropicPromptCacheStrategy.class);
        assertThat(s.providerName()).isEqualTo("anthropic");
    }

    @Test
    @DisplayName("resolve returns OpenAiPromptCacheStrategy for openai and gemini when cache is enabled")
    void resolve_OpenAiAndGeminiWhenEnabled_ReturnsOpenAiStrategy() {
        // given
        PromptCacheStrategyResolver resolver = build(true, Map.of("openai", true, "gemini", true));

        // then
        assertThat(resolver.resolve("openai")).isInstanceOf(OpenAiPromptCacheStrategy.class);
        assertThat(resolver.resolve("gemini")).isInstanceOf(OpenAiPromptCacheStrategy.class);
    }

    @Test
    @DisplayName("resolve always returns NoopPromptCacheStrategy for lmstudio and minimax")
    void resolve_LmstudioOrMinimax_AlwaysNoop() {
        // given
        PromptCacheStrategyResolver resolver = build(true, Map.of("lmstudio", true, "minimax", true));

        // then
        assertThat(resolver.resolve("lmstudio")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve("minimax")).isInstanceOf(NoopPromptCacheStrategy.class);
    }

    @Test
    @DisplayName("resolve returns NoopPromptCacheStrategy for all providers when master toggle is off")
    void resolve_MasterToggleOff_AlwaysNoop() {
        // given
        PromptCacheStrategyResolver resolver = build(false, Map.of("anthropic", true));

        // then
        assertThat(resolver.resolve("anthropic")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve("openai")).isInstanceOf(NoopPromptCacheStrategy.class);
    }

    @Test
    @DisplayName("resolve returns Noop only for the provider whose per-provider toggle is off")
    void resolve_PerProviderToggleOff_OnlyThatProviderNoop() {
        // given
        PromptCacheStrategyResolver resolver = build(true, Map.of("anthropic", false, "openai", true));

        // then
        assertThat(resolver.resolve("anthropic")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve("openai")).isInstanceOf(OpenAiPromptCacheStrategy.class);
    }

    @Test
    @DisplayName("resolve returns NoopPromptCacheStrategy for unknown or null provider")
    void resolve_UnknownProvider_ReturnsNoop() {
        // given
        PromptCacheStrategyResolver resolver = build(true, Map.of());

        // then
        assertThat(resolver.resolve("doesnotexist")).isInstanceOf(NoopPromptCacheStrategy.class);
        assertThat(resolver.resolve(null)).isInstanceOf(NoopPromptCacheStrategy.class);
    }

    @Test
    @DisplayName("resolve returns the same Noop instance on repeated calls for the same provider")
    void resolve_NoopReusedAcrossCallsForSameProvider() {
        // given
        PromptCacheStrategyResolver resolver = build(true, Map.of());

        // when
        PromptCacheStrategy a = resolver.resolve("foo");
        PromptCacheStrategy b = resolver.resolve("foo");

        // then
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
