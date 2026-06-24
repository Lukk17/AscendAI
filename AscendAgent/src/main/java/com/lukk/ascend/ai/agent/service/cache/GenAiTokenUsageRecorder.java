package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;

/**
 * Records the standard {@code gen_ai.client.token.usage} counter so that the Grafana
 * token-cost dashboard query {@code gen_ai_client_token_usage_total{gen_ai_system,
 * gen_ai_request_model, gen_ai_token_type}} resolves to actual series.
 *
 * <p>Called from every {@link PromptCacheStrategy#recordOutcome} implementation so the
 * counter is emitted for all providers regardless of whether prompt-caching is active.
 */
final class GenAiTokenUsageRecorder {

    private static final String METRIC_NAME = "gen_ai.client.token.usage";
    private static final String TAG_GEN_AI_SYSTEM = "gen_ai_system";
    private static final String TAG_MODEL = "gen_ai_request_model";
    private static final String TAG_TOKEN_TYPE = "gen_ai_token_type";
    private static final String TOKEN_TYPE_INPUT = "input";
    private static final String TOKEN_TYPE_OUTPUT = "output";
    private static final String TOKEN_TYPE_TOTAL = "total";

    private GenAiTokenUsageRecorder() {
    }

    /**
     * Emits {@code gen_ai.client.token.usage} counters for input, output, and total
     * tokens from {@code response}. Does nothing when {@code response} is {@code null}
     * or when the response carries no usage data.
     *
     * @param registry     the meter registry to record into
     * @param response     the chat response carrying token usage metadata
     * @param genAiSystem  value for the {@code gen_ai_system} tag (e.g. "openai", "anthropic")
     */
    static void record(MeterRegistry registry, ChatResponse response, String genAiSystem) {
        if (response == null) {
            return;
        }

        Usage usage = response.getMetadata().getUsage();
        if (usage == null) {
            return;
        }

        String model = resolveModel(response);
        int input = usage.getPromptTokens() != null ? usage.getPromptTokens() : 0;
        int output = usage.getCompletionTokens() != null ? usage.getCompletionTokens() : 0;
        int total = usage.getTotalTokens() != null ? usage.getTotalTokens() : input + output;

        incrementCounter(registry, genAiSystem, model, TOKEN_TYPE_INPUT, input);
        incrementCounter(registry, genAiSystem, model, TOKEN_TYPE_OUTPUT, output);
        incrementCounter(registry, genAiSystem, model, TOKEN_TYPE_TOTAL, total);
    }

    private static void incrementCounter(MeterRegistry registry, String genAiSystem,
                                         String model, String tokenType, int amount) {
        Counter.builder(METRIC_NAME)
                .tag(TAG_GEN_AI_SYSTEM, genAiSystem)
                .tag(TAG_MODEL, model)
                .tag(TAG_TOKEN_TYPE, tokenType)
                .register(registry)
                .increment(amount);
    }

    private static String resolveModel(ChatResponse response) {
        try {
            String model = response.getMetadata().getModel();
            return (model != null && !model.isBlank()) ? model : "unknown";
        } catch (Exception ignored) {
            return "unknown";
        }
    }
}
