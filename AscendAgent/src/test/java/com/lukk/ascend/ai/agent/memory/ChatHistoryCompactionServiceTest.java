package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import org.junit.jupiter.api.BeforeEach;
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
    void maybeCompact_DisabledByMaster_NoLlmCall() {
        compactionProperties.setEnabled(false);

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(repository, redisTemplate, chatModelResolver, transactionTemplate);
    }

    @Test
    void maybeCompact_BothBackendsDisabled_NoLlmCall() {
        historyProperties.getRedis().setEnabled(false);
        historyProperties.getPostgres().setEnabled(false);

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(repository, redisTemplate, chatModelResolver, transactionTemplate);
    }

    @Test
    void maybeCompact_BelowTurnTriggerAndBelowTokenTrigger_NoLlmCall() {
        when(repository.findAllHistoryOrdered(CONVERSATION_ID)).thenReturn(buildHistory(5));

        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(chatModelResolver, transactionTemplate);
        verify(redisTemplate, never()).opsForList();
    }

    @Test
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
    void resolveTarget_NoOverride_UsesPrimaryProviderDefault() {
        var t = service.resolveTarget("anthropic", CompactionOverride.EMPTY);

        assertThat(t.provider()).isEqualTo("anthropic");
        assertThat(t.model()).isEqualTo("claude-haiku-4-5");
    }

    @Test
    void resolveTarget_OverrideProviderOnly_UsesOverrideProviderDefault() {
        var t = service.resolveTarget("anthropic", new CompactionOverride("openai", null));

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    void resolveTarget_OverrideModelOnly_UsesPrimaryProviderWithOverrideModel() {
        var t = service.resolveTarget("anthropic", new CompactionOverride(null, "claude-opus-4-6"));

        assertThat(t.provider()).isEqualTo("anthropic");
        assertThat(t.model()).isEqualTo("claude-opus-4-6");
    }

    @Test
    void resolveTarget_BothOverrides_UsesBoth() {
        var t = service.resolveTarget("anthropic", new CompactionOverride("openai", "gpt-5.4"));

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-5.4");
    }

    @Test
    void contextWindow_KnownProvider_ReturnsKnownDefault() {
        assertThat(service.contextWindow("anthropic")).isEqualTo(200_000);
        assertThat(service.contextWindow("openai")).isEqualTo(128_000);
        assertThat(service.contextWindow("gemini")).isEqualTo(1_000_000);
        assertThat(service.contextWindow("lmstudio")).isEqualTo(8_192);
    }

    @Test
    void contextWindow_UnknownOrNull_FallsBackToLocalSafeDefault() {
        assertThat(service.contextWindow(null)).isEqualTo(8_192);
        assertThat(service.contextWindow("unknown-provider")).isEqualTo(8_192);
    }

    @Test
    void estimateTokens_ApproximatesByCharsOverFour() {
        List<ChatHistory> hist = List.of(
                row("user", "1234"),
                row("assistant", "12345678"));

        assertThat(service.estimateTokens(hist)).isEqualTo(1 + 2);
    }

    @Test
    void maybeCompact_WhenAnyExceptionThrows_Swallowed() {
        when(repository.findAllHistoryOrdered(CONVERSATION_ID))
                .thenThrow(new RuntimeException("postgres down"));

        // Must not throw.
        service.maybeCompact(CONVERSATION_ID, PRIMARY_PROVIDER, CompactionOverride.EMPTY);
    }

    @Test
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
