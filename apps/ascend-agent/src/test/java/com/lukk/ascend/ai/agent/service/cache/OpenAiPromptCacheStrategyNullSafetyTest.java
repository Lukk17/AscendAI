package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.test.LogCapture;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.openai.api.OpenAiApi;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class OpenAiPromptCacheStrategyNullSafetyTest {

    private final OpenAiPromptCacheStrategy strategy = new OpenAiPromptCacheStrategy("openai", new SimpleMeterRegistry());

    @RegisterExtension
    final LogCapture logs = LogCapture.forClass(OpenAiPromptCacheStrategy.class);

    @Test
    @DisplayName("recordOutcome does not throw when usage is null")
    void recordOutcome_NullUsage_DoesNotThrow() {
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

    @Test
    @DisplayName("recordOutcome does not throw when PromptTokensDetails is null inside OpenAiApi.Usage")
    void recordOutcome_NullPromptTokensDetails_DoesNotThrow() {
        // given
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, null, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        ThrowingCallable recordOutcome = () -> strategy.recordOutcome("user", response);

        // then
        assertThatCode(recordOutcome).doesNotThrowAnyException();
        assertThat(logs.messages()).isEmpty();
    }

    @Test
    @DisplayName("recordOutcome logs cold-start when cachedTokens is 0")
    void recordOutcome_CachedTokensZero_LogsColdStart() {
        // given
        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 0);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        assertThat(logs.messages()).singleElement().asString()
                .endsWith("provider=openai user=user hit=false cached_tokens=0 prompt_tokens=1024");
    }

    @Test
    @DisplayName("buildOptions returns null when model is an empty string")
    void buildOptions_EmptyModel_ReturnsNull() {
        // then
        assertThat(strategy.buildOptions("")).isNull();
    }

    @Test
    @DisplayName("buildOptions returns null when model is whitespace")
    void buildOptions_WhitespaceModel_ReturnsNull() {
        // then
        assertThat(strategy.buildOptions("   ")).isNull();
    }

    @Test
    @DisplayName("recordOutcome uses 0 for prompt tokens when getPromptTokens() returns null (mocked Usage)")
    void recordOutcome_MockedUsageWithNullPromptTokens_UsesZero() {
        // given - DefaultUsage converts null to 0 internally; mocked Usage keeps null from getPromptTokens()
        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 128);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
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
                .endsWith("provider=openai user=user hit=true cached_tokens=128 prompt_tokens=0");
    }
}
