package com.lukk.ascend.ai.agent.service.cache;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class NoopPromptCacheStrategyTest {

    @Test
    @DisplayName("buildOptions returns null when model is null")
    void buildOptions_NullModel_ReturnsNull() {
        // given
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("lmstudio");

        // then
        assertThat(strategy.buildOptions(null)).isNull();
    }

    @Test
    @DisplayName("buildOptions returns generic ChatOptions with the model set")
    void buildOptions_WithModel_ReturnsGenericChatOptionsWithModel() {
        // given
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("minimax");

        // when
        var opts = strategy.buildOptions("MiniMax-M2.5");

        // then
        assertThat(opts).isNotNull();
        assertThat(opts.getModel()).isEqualTo("MiniMax-M2.5");
    }

    @Test
    @DisplayName("recordOutcome is a no-op and does not throw")
    void recordOutcome_DoesNothing() {
        // then
        new NoopPromptCacheStrategy("x").recordOutcome("u", null);
    }

    @Test
    @DisplayName("isCacheConfigError always returns false regardless of exception")
    void isCacheConfigError_AlwaysFalse() {
        // then
        assertThat(new NoopPromptCacheStrategy("x").isCacheConfigError(new RuntimeException("cache_control bad"))).isFalse();
    }
}
