package com.lukk.ascend.ai.agent.service.cache;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class NoopPromptCacheStrategyTest {

    @Test
    void buildOptions_NullModel_ReturnsNull() {
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("lmstudio");
        assertThat(strategy.buildOptions(null)).isNull();
    }

    @Test
    void buildOptions_WithModel_ReturnsGenericChatOptionsWithModel() {
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("minimax");
        var opts = strategy.buildOptions("MiniMax-M2.5");
        assertThat(opts).isNotNull();
        assertThat(opts.getModel()).isEqualTo("MiniMax-M2.5");
    }

    @Test
    void recordOutcome_DoesNothing() {
        new NoopPromptCacheStrategy("x").recordOutcome("u", null);
    }

    @Test
    void isCacheConfigError_AlwaysFalse() {
        assertThat(new NoopPromptCacheStrategy("x").isCacheConfigError(new RuntimeException("cache_control bad"))).isFalse();
    }
}
