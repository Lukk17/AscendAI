package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.test.LogCapture;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.ai.anthropic.api.AnthropicApi;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AnthropicPromptCacheStrategyNullSafetyTest {

    private final AnthropicPromptCacheStrategy strategy = new AnthropicPromptCacheStrategy(new SimpleMeterRegistry());

    @RegisterExtension
    final LogCapture logs = LogCapture.forClass(AnthropicPromptCacheStrategy.class);

    @Test
    @DisplayName("recordOutcome handles null promptTokens (uses 0 as fallback)")
    void recordOutcome_NullPromptTokens_UsesZeroFallback() {
        // given - AnthropicApi.Usage with both cache fields set, but wrapper Usage.getPromptTokens() returns null
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(null, 100, 0, 50);
        Usage usage = new DefaultUsage(null, 100, null, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=anthropic user=user hit=true cache_read_tokens=50 cache_creation_tokens=0 prompt_tokens=0");
    }

    @Test
    @DisplayName("recordOutcome handles null cacheReadInputTokens (logs 0)")
    void recordOutcome_NullCacheReadTokens_LogsZero() {
        // given - AnthropicApi.Usage with null cacheRead
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(200, 100, 300, null);
        Usage usage = new DefaultUsage(200, 100, 300, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=anthropic user=user hit=false cache_read_tokens=0 cache_creation_tokens=300 prompt_tokens=200");
    }

    @Test
    @DisplayName("recordOutcome handles null cacheCreationInputTokens (logs 0)")
    void recordOutcome_NullCacheCreationTokens_LogsZero() {
        // given - AnthropicApi.Usage with null cacheCreate
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(200, 100, null, 50);
        Usage usage = new DefaultUsage(200, 100, 300, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=anthropic user=user hit=true cache_read_tokens=50 cache_creation_tokens=0 prompt_tokens=200");
    }

    @Test
    @DisplayName("isCacheConfigError returns true for '400' + 'cache' pattern (third condition)")
    void isCacheConfigError_400AndCache_ReturnsTrue() {
        // then
        assertThat(strategy.isCacheConfigError(new RuntimeException("HTTP 400 invalid cache configuration")))
                .isTrue();
    }

    @Test
    @DisplayName("isCacheConfigError returns true when message contains 'cache-control' only (second condition)")
    void isCacheConfigError_CacheControlHyphen_ReturnsTrue() {
        // then
        assertThat(strategy.isCacheConfigError(new RuntimeException("invalid cache-control header")))
                .isTrue();
    }

    @Test
    @DisplayName("isCacheConfigError returns false for unrelated 400 error without 'cache'")
    void isCacheConfigError_400WithoutCache_ReturnsFalse() {
        // then
        assertThat(strategy.isCacheConfigError(new RuntimeException("HTTP 400 bad request")))
                .isFalse();
    }

    @Test
    @DisplayName("recordOutcome uses 0 for prompt tokens when getPromptTokens() returns null")
    void recordOutcome_NullPromptTokensFromUsage_UsesZero() {
        // given
        // inputTokens=null
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(null, 100, 300, 50);
        // promptTokens=null
        Usage usage = new DefaultUsage(null, 100, null, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=anthropic user=user hit=true cache_read_tokens=50 cache_creation_tokens=300 prompt_tokens=0");
    }

    @Test
    @DisplayName("recordOutcome logs hit=false when cacheReadInputTokens is non-null but zero")
    void recordOutcome_CacheReadTokensZero_LogsHitFalse() {
        // given - read = 0 (non-null but zero) -> hit = (read != null && read > 0) = false
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(200, 100, 300, 0);
        Usage usage = new DefaultUsage(200, 100, 300, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=anthropic user=user hit=false cache_read_tokens=0 cache_creation_tokens=300 prompt_tokens=200");
    }

    @Test
    @DisplayName("recordOutcome uses 0 for prompt tokens when getPromptTokens() returns null (mocked Usage)")
    void recordOutcome_MockedUsageWithNullPromptTokens_UsesZeroFallback() {
        // given - DefaultUsage converts null to 0 internally; mocked Usage keeps null from getPromptTokens()
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(null, 100, 50, 25);
        Usage usage = mock(Usage.class);
        when(usage.getNativeUsage()).thenReturn(native_);
        when(usage.getPromptTokens()).thenReturn(null);
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(usage);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=anthropic user=user hit=true cache_read_tokens=25 cache_creation_tokens=50 prompt_tokens=0");
    }

    @Test
    @DisplayName("recordOutcome does not throw when Usage is null in metadata")
    void recordOutcome_NullUsageInMetadata_DoesNotThrow() {
        // given
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(null);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        ThrowingCallable recordOutcome = () -> strategy.recordOutcome("user", response);

        // then
        assertThatCode(recordOutcome).doesNotThrowAnyException();
        assertThat(logs.messages()).isEmpty();
    }
}
