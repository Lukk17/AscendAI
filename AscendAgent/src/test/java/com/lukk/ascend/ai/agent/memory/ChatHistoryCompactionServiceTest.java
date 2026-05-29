package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatHistoryCompactionServiceTest {

    private static final String CONVERSATION_ID = "user1";
    private static final String PRIMARY_PROVIDER = "anthropic";

    @Mock
    private ChatHistoryRepository repository;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ListOperations<String, String> listOperations;

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private TransactionTemplate transactionTemplate;

    private ChatHistoryCompactionProperties compactionProperties;
    private ChatHistoryProperties historyProperties;
    private AiProviderProperties aiProviderProperties;
    private ChatHistoryCompactionService service;

    @BeforeEach
    void setUp() {
        compactionProperties = new ChatHistoryCompactionProperties();
        compactionProperties.setEnabled(true);
        compactionProperties.setTurnTrigger(20);
        compactionProperties.setKeepRecentTurns(8);
        compactionProperties.setMaxSummaryTokens(800);
        compactionProperties.setProviderDefaults(Map.of(
                "anthropic", "claude-haiku-4-5",
                "openai", "gpt-4o-mini",
                "gemini", "gemini-flash-lite-latest"));

        historyProperties = new ChatHistoryProperties();

        aiProviderProperties = new AiProviderProperties();
        aiProviderProperties.setDefaultProvider("anthropic");

        service = new ChatHistoryCompactionService(compactionProperties, historyProperties, repository,
                redisTemplate, new ObjectMapper(), chatModelResolver, aiProviderProperties, transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact does nothing when compaction is disabled by master toggle")
    void maybeCompact_DisabledByMaster_NoLlmCall() {
        compactionProperties.setEnabled(false);

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(repository, redisTemplate, chatModelResolver, transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact does nothing when both Redis and Postgres backends are disabled")
    void maybeCompact_BothBackendsDisabled_NoLlmCall() {
        historyProperties.getRedis().setEnabled(false);
        historyProperties.getPostgres().setEnabled(false);

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(repository, redisTemplate, chatModelResolver, transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact skips LLM call when history is below turn and token thresholds")
    void maybeCompact_BelowTurnTriggerAndBelowTokenTrigger_NoLlmCall() {
        when(repository.findAllHistoryOrdered(CONVERSATION_ID)).thenReturn(buildHistory(5));

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(chatModelResolver, transactionTemplate);
        verify(redisTemplate, never()).opsForList();
    }

    @Test
    @DisplayName("maybeCompact attempts to invoke chat model when history exceeds turn trigger")
    void maybeCompact_AboveTurnTriggerWithoutSummary_TriesToInvokeChatModel() {
        when(repository.findAllHistoryOrdered(CONVERSATION_ID)).thenReturn(buildHistory(25));
        when(chatModelResolver.resolve("anthropic")).thenThrow(new IllegalArgumentException("provider unavailable in unit test"));

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        // Trigger fired and we tried to resolve the model.
        verify(chatModelResolver).resolve("anthropic");
        // No persistence happens because the LLM call failed; service swallows.
        verifyNoInteractions(transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact skips LLM call when history already has a summary and raw turns are below trigger")
    void maybeCompact_AlreadySummarisedAndBelowTriggerWithoutTheSummary_NoLlmCall() {
        // history has 1 summary + 18 raw turns -> turns(history) - 1 = 18 < 20 => skip
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(summary());
        hist.addAll(buildHistory(18));
        when(repository.findAllHistoryOrdered(CONVERSATION_ID)).thenReturn(hist);

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(chatModelResolver, transactionTemplate);
    }

    @Test
    @DisplayName("resolveTarget uses primary provider default model when no override is set")
    void resolveTarget_NoOverride_UsesPrimaryProviderDefault() {
        var t = service.resolveTarget("anthropic", CompactionOverride.EMPTY);

        assertThat(t.provider()).isEqualTo("anthropic");
        assertThat(t.model()).isEqualTo("claude-haiku-4-5");
    }

    @Test
    @DisplayName("resolveTarget uses override provider's default model when provider is overridden")
    void resolveTarget_OverrideProviderOnly_UsesOverrideProviderDefault() {
        var t = service.resolveTarget("anthropic", new CompactionOverride("openai", null));

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget uses primary provider with overridden model when only model is overridden")
    void resolveTarget_OverrideModelOnly_UsesPrimaryProviderWithOverrideModel() {
        var t = service.resolveTarget("anthropic", new CompactionOverride(null, "claude-opus-4-6"));

        assertThat(t.provider()).isEqualTo("anthropic");
        assertThat(t.model()).isEqualTo("claude-opus-4-6");
    }

    @Test
    @DisplayName("resolveTarget uses both overridden provider and model when both are set")
    void resolveTarget_BothOverrides_UsesBoth() {
        var t = service.resolveTarget("anthropic", new CompactionOverride("openai", "gpt-5.4"));

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-5.4");
    }

    @Test
    @DisplayName("contextWindow returns known default token counts for all supported providers")
    void contextWindow_KnownProvider_ReturnsKnownDefault() {
        assertThat(service.contextWindow("anthropic")).isEqualTo(200_000);
        assertThat(service.contextWindow("openai")).isEqualTo(128_000);
        assertThat(service.contextWindow("gemini")).isEqualTo(1_000_000);
        assertThat(service.contextWindow("lmstudio")).isEqualTo(8_192);
    }

    @Test
    @DisplayName("contextWindow falls back to 8192 safe default for null or unknown provider")
    void contextWindow_UnknownOrNull_FallsBackToLocalSafeDefault() {
        assertThat(service.contextWindow(null)).isEqualTo(8_192);
        assertThat(service.contextWindow("unknown-provider")).isEqualTo(8_192);
    }

    @Test
    @DisplayName("estimateTokens approximates token count as total chars divided by four")
    void estimateTokens_ApproximatesByCharsOverFour() {
        List<ChatHistory> hist = List.of(
                row("user", "1234"),
                row("assistant", "12345678"));

        assertThat(service.estimateTokens(hist)).isEqualTo(1 + 2);
    }

    @Test
    @DisplayName("maybeCompact swallows any exception so the caller's turn is never broken")
    void maybeCompact_WhenAnyExceptionThrows_Swallowed() {
        when(repository.findAllHistoryOrdered(CONVERSATION_ID))
                .thenThrow(new RuntimeException("postgres down"));

        // Must not throw.
        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);
    }

    @Test
    @DisplayName("maybeCompact treats null CompactionOverride the same as EMPTY")
    void maybeCompact_WhenOverrideIsNull_TreatedAsEmpty() {
        when(repository.findAllHistoryOrdered(CONVERSATION_ID)).thenReturn(buildHistory(5));

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, null);

        // 5 turns, well below trigger -> no resolution, no LLM
        verifyNoInteractions(chatModelResolver);
    }

    private List<ChatHistory> buildHistory(int turns) {
        List<ChatHistory> hist = new ArrayList<>();
        for (int i = 0; i < turns; i++) {
            String role = i % 2 == 0 ? "user" : "assistant";
            hist.add(new ChatHistory((long) (i + 1), CONVERSATION_ID, role, "msg " + i, LocalDateTime.now().minusMinutes(turns - i)));
        }
        return hist;
    }

    private ChatHistory row(String role, String content) {
        return new ChatHistory(1L, CONVERSATION_ID, role, content, LocalDateTime.now());
    }

    private ChatHistory summary() {
        return new ChatHistory(0L, CONVERSATION_ID, "system",
                ChatHistoryCompactionService.SUMMARY_MARKER + " older context goes here",
                LocalDateTime.now().minusHours(1));
    }
}
