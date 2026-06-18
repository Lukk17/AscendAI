package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.model.ChatResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class GenAiTokenUsageRecorderTest {

    @Test
    @DisplayName("record emits input counter with correct amount and tags")
    void record_EmitsInputCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        ChatResponse response = buildResponse(registry, "gpt-4o", 200, 80);

        // when
        GenAiTokenUsageRecorder.record(registry, response, "openai");

        // then
        Counter counter = registry.find("gen_ai.client.token.usage")
                .tag("gen_ai_system", "openai")
                .tag("gen_ai_request_model", "gpt-4o")
                .tag("gen_ai_token_type", "input")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(200.0);
    }

    @Test
    @DisplayName("record emits output counter with correct amount and tags")
    void record_EmitsOutputCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        ChatResponse response = buildResponse(registry, "claude-sonnet-4-5", 150, 60);

        // when
        GenAiTokenUsageRecorder.record(registry, response, "anthropic");

        // then
        Counter counter = registry.find("gen_ai.client.token.usage")
                .tag("gen_ai_system", "anthropic")
                .tag("gen_ai_request_model", "claude-sonnet-4-5")
                .tag("gen_ai_token_type", "output")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(60.0);
    }

    @Test
    @DisplayName("record emits total counter as sum of input and output when Usage.getTotalTokens is set")
    void record_EmitsTotalCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        ChatResponse response = buildResponse(registry, "gemini-flash", 100, 40);

        // when
        GenAiTokenUsageRecorder.record(registry, response, "gemini");

        // then
        Counter counter = registry.find("gen_ai.client.token.usage")
                .tag("gen_ai_system", "gemini")
                .tag("gen_ai_request_model", "gemini-flash")
                .tag("gen_ai_token_type", "total")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(140.0);
    }

    @Test
    @DisplayName("record uses 'unknown' as model when ChatResponseMetadata.getModel returns null")
    void record_NullModelInMetadata_UsesUnknown() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        DefaultUsage usage = new DefaultUsage(50, 20, 70, null);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        GenAiTokenUsageRecorder.record(registry, response, "lmstudio");

        // then — model tag falls back to "unknown"
        Counter counter = registry.find("gen_ai.client.token.usage")
                .tag("gen_ai_system", "lmstudio")
                .tag("gen_ai_request_model", "unknown")
                .tag("gen_ai_token_type", "input")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(50.0);
    }

    @Test
    @DisplayName("record does nothing when response is null")
    void record_NullResponse_DoesNotThrow() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();

        // when / then — no exception, no counters registered
        GenAiTokenUsageRecorder.record(registry, null, "openai");
        assertThat(registry.find("gen_ai.client.token.usage").counters()).isEmpty();
    }

    @Test
    @DisplayName("record does nothing when metadata returns null usage")
    void record_NullUsage_DoesNotThrow() {
        // given — metadata mock returns null for getUsage()
        MeterRegistry registry = new SimpleMeterRegistry();
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(null);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when / then — no exception, no counters registered
        GenAiTokenUsageRecorder.record(registry, response, "openai");
        assertThat(registry.find("gen_ai.client.token.usage").counters()).isEmpty();
    }

    private ChatResponse buildResponse(MeterRegistry ignoredRegistry, String modelName,
                                       int inputTokens, int outputTokens) {
        DefaultUsage usage = new DefaultUsage(inputTokens, outputTokens, inputTokens + outputTokens, null);
        ChatResponseMetadata md = ChatResponseMetadata.builder()
                .model(modelName)
                .usage(usage)
                .build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        return response;
    }
}
