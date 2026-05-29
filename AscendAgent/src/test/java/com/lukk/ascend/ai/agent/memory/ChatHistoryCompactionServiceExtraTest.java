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
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Additional branch coverage for ChatHistoryCompactionService: redis-only, postgres-only,
 * token-triggered compaction, already-summarised + recent turns above trigger, prefix clamping,
 * summariser returning null / blank / missing marker, provider fallback to default.
 */
@ExtendWith(MockitoExtension.class)
class ChatHistoryCompactionServiceExtraTest {

    private static final String CONV_ID = "test-convo";
    private static final String PROVIDER = "openai";

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

    @Mock
    private ChatModel chatModel;

    private ChatHistoryCompactionProperties compactionProperties;
    private ChatHistoryProperties historyProperties;
    private AiProviderProperties aiProviderProperties;
    private ChatHistoryCompactionService service;

    @BeforeEach
    void setUp() {
        compactionProperties = new ChatHistoryCompactionProperties();
        compactionProperties.setEnabled(true);
        compactionProperties.setTurnTrigger(10);
        compactionProperties.setKeepRecentTurns(5);
        compactionProperties.setTokenTriggerFraction(0.5);
        compactionProperties.setMaxSummaryTokens(400);
        compactionProperties.setProviderDefaults(Map.of(
                "openai", "gpt-4o-mini",
                "anthropic", "claude-haiku-4-5"));

        historyProperties = new ChatHistoryProperties();

        aiProviderProperties = new AiProviderProperties();
        aiProviderProperties.setDefaultProvider("openai");

        service = new ChatHistoryCompactionService(
                compactionProperties, historyProperties, repository,
                redisTemplate, new ObjectMapper(), chatModelResolver,
                aiProviderProperties, transactionTemplate);
    }

    // ------------------------------------------------------------------ redis-only path

    @Test
    @DisplayName("maybeCompact does nothing when only Redis is enabled but history list is empty")
    void maybeCompact_RedisOnlyAndHistoryEmpty_SkipsCompaction() {
        // postgres is off, redis is on; repository returns empty since postgres is off
        historyProperties.getPostgres().setEnabled(false);
        historyProperties.getRedis().setEnabled(true);

        // Because postgresOn is false, history is List.of() -> skips on isEmpty()
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(chatModelResolver, transactionTemplate);
    }

    // ------------------------------------------------------------------ postgres-only path

    @Test
    @DisplayName("applyToRedis is skipped when Redis is disabled but Postgres is enabled")
    void maybeCompact_PostgresOnlyAndAboveTrigger_AppliesOnlyToPostgres() {
        historyProperties.getRedis().setEnabled(false);
        historyProperties.getPostgres().setEnabled(true);

        // 15 turns – above default trigger of 10
        List<ChatHistory> history = buildHistory(15);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("test – provider unavailable"));

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // Redis should never be touched
        verifyNoInteractions(redisTemplate);
        verify(chatModelResolver).resolve(PROVIDER);
    }

    // ------------------------------------------------------------------ token-triggered path

    @Test
    @DisplayName("maybeCompact fires when only token threshold is exceeded (turns below turn trigger)")
    void maybeCompact_TokenTriggered_TriesToInvokeChatModel() {
        // 5 turns (below turn-trigger of 10), but very long content -> token-trigger fires
        List<ChatHistory> history = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            // Each row has enough characters to push estimated tokens over 50% of lmstudio's 8192 window
            String bigContent = "x".repeat(20_000); // ~5000 tokens per row, 25000 total >> 4096 threshold
            history.add(new ChatHistory((long) (i + 1), CONV_ID, "user", bigContent, LocalDateTime.now()));
        }
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(anyString())).thenThrow(new IllegalArgumentException("unavailable"));

        // Use lmstudio as provider (8192 context window) so token trigger fires at 4096 tokens
        service.maybeCompact(CONV_ID, "lmstudio", CompactionOverride.EMPTY);

        verify(chatModelResolver).resolve(anyString());
    }

    // ------------------------------------------------------------------ already-summarised but above trigger

    @Test
    @DisplayName("maybeCompact fires when first entry is a summary but remaining turns exceed trigger")
    void maybeCompact_AlreadySummarisedAndRemainingTurnsAboveTrigger_TriesToInvokeChatModel() {
        // 1 summary + 12 raw turns: turns-1 = 12 >= trigger(10) -> should proceed
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(summary());
        hist.addAll(buildHistory(12));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verify(chatModelResolver).resolve(PROVIDER);
    }

    // ------------------------------------------------------------------ alreadySummarised AND (turns-1) < turnTrigger

    @Test
    @DisplayName("maybeCompact skips LLM call when first entry is a summary and turns-1 is below trigger")
    void maybeCompact_AlreadySummarisedAndTurnsMinusOneBelowTrigger_SkipsCompaction() {
        // turns = turnTrigger (10), so turnTriggered = true (outer check passes).
        // alreadySummarised = true. turns-1 = 9 < 10 = true -> return noCompaction (line 137 true branch).
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(summary());
        hist.addAll(buildHistory(9)); // 1 summary + 9 raw = 10 total
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // compaction skipped -> no LLM call
        verifyNoInteractions(chatModelResolver);
    }

    // ------------------------------------------------------------------ prefix clamping: prefixCount >= turns

    @Test
    @DisplayName("computePrefixCount clamps to turns-1 when keepRecentTurns is 0")
    void computePrefixCount_WhenKeepRecentZero_ClampsToTurnsMinusOne() {
        compactionProperties.setKeepRecentTurns(0);
        // Rebuild service with updated properties
        service = new ChatHistoryCompactionService(
                compactionProperties, historyProperties, repository,
                redisTemplate, new ObjectMapper(), chatModelResolver,
                aiProviderProperties, transactionTemplate);

        List<ChatHistory> history = buildHistory(12); // 12 turns, keep 0 -> prefixCount = 12 > 12-1=11 => clamp to 11
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("test"));

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // service still resolves the model (prefixCount=11 >= 1)
        verify(chatModelResolver).resolve(PROVIDER);
    }

    // ------------------------------------------------------------------ summariser returns null / blank

    @Test
    @DisplayName("maybeCompact skips persistence when summariser returns null response content")
    void maybeCompact_SummariserReturnsNull_SkipsPersistence() {
        // Pre-build the response before entering any when() chain
        ChatResponse nullResponse = buildChatResponseWithContent(null);

        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(nullResponse);

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact skips persistence when summariser returns blank response content")
    void maybeCompact_SummariserReturnsBlank_SkipsPersistence() {
        ChatResponse blankResponse = buildChatResponseWithContent("   ");

        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(blankResponse);

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact skips persistence when summariser output exceeds hard-cap token count")
    void maybeCompact_SummariserExceedsHardCap_SkipsPersistence() {
        // maxSummaryTokens = 400, hardCap = 600 tokens -> 2400 chars; produce a string much longer
        String oversized = "A".repeat(12_000); // ~3000 tokens
        ChatResponse bigResponse = buildChatResponseWithContent("[Conversation summary] " + oversized);

        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(bigResponse);

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verifyNoInteractions(transactionTemplate);
    }

    // ------------------------------------------------------------------ summariser auto-prepend marker

    @Test
    @DisplayName("maybeCompact proceeds to persistence when summariser output is missing the marker (auto-prepend)")
    void maybeCompact_SummariserMissingMarker_AutoPrepends() {
        // No [Conversation summary] prefix -> service prepends it and proceeds
        historyProperties.getRedis().setEnabled(false); // only postgres, simpler assertions
        ChatResponse markerlessResponse = buildChatResponseWithContent("Short valid summary without marker.");

        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(markerlessResponse);

        // TransactionTemplate.executeWithoutResult should be called
        doAnswer(inv -> {
            Consumer<org.springframework.transaction.TransactionStatus> callback = inv.getArgument(0);
            callback.accept(org.mockito.Mockito.mock(org.springframework.transaction.TransactionStatus.class));
            return null;
        }).when(transactionTemplate).executeWithoutResult(any());

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verify(transactionTemplate).executeWithoutResult(any());
    }

    // ------------------------------------------------------------------ resolveTarget: blank primary provider

    @Test
    @DisplayName("resolveTarget falls back to aiProviderProperties.defaultProvider when primaryProvider is blank")
    void resolveTarget_BlankPrimaryProvider_UsesDefaultProvider() {
        var t = service.resolveTarget("", CompactionOverride.EMPTY);

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget falls back to aiProviderProperties.defaultProvider when primaryProvider is null")
    void resolveTarget_NullPrimaryProvider_UsesDefaultProvider() {
        var t = service.resolveTarget(null, CompactionOverride.EMPTY);

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    // ------------------------------------------------------------------ contextWindow minimax

    @Test
    @DisplayName("contextWindow returns 200000 for minimax provider")
    void contextWindow_MinimaxProvider_Returns200k() {
        assertThat(service.contextWindow("minimax")).isEqualTo(200_000);
    }

    // ------------------------------------------------------------------ applyToRedis branch coverage

    @Test
    @DisplayName("maybeCompact writes to Redis when only Redis is enabled and compaction fires")
    void maybeCompact_RedisEnabledAndAboveTrigger_WritesToRedis() {
        historyProperties.getPostgres().setEnabled(true);
        historyProperties.getRedis().setEnabled(true);

        ChatResponse conciseResponse = buildChatResponseWithContent("[Conversation summary] concise summary");
        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(conciseResponse);
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        doAnswer(inv -> {
            Consumer<org.springframework.transaction.TransactionStatus> callback = inv.getArgument(0);
            callback.accept(org.mockito.Mockito.mock(org.springframework.transaction.TransactionStatus.class));
            return null;
        }).when(transactionTemplate).executeWithoutResult(any());

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verify(listOperations).trim(anyString(), any(Long.class), any(Long.class));
        verify(listOperations).leftPush(anyString(), anyString());
    }

    // ------------------------------------------------------------------ decideCompaction: prefixCount < 1

    @Test
    @DisplayName("maybeCompact skips when prefixCount is 0 (single history entry triggers token threshold)")
    void maybeCompact_SingleEntryTokenTriggered_PrefixCountZeroSkips() {
        compactionProperties.setKeepRecentTurns(5); // keepRecent = 5 > 1 turn -> prefixCount = 0
        compactionProperties.setTurnTrigger(100); // turn trigger not hit
        compactionProperties.setTokenTriggerFraction(0.00001); // very low fraction -> token trigger fires with 1 entry
        service = new ChatHistoryCompactionService(
                compactionProperties, historyProperties, repository,
                redisTemplate, new ObjectMapper(), chatModelResolver,
                aiProviderProperties, transactionTemplate);

        // 1-entry history with sufficient content to trigger token threshold
        ChatHistory single = new ChatHistory(1L, CONV_ID, "user", "X".repeat(10_000), LocalDateTime.now());
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(List.of(single));

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // prefixCount = 0 < 1 -> skip (no LLM call)
        verifyNoInteractions(chatModelResolver);
    }

    // ------------------------------------------------------------------ additional targeted coverage

    @Test
    @DisplayName("estimateTokens skips entries with null content")
    void estimateTokens_NullContent_IsSkipped() {
        List<ChatHistory> hist = List.of(
                new ChatHistory(1L, CONV_ID, "user", null, LocalDateTime.now()),
                new ChatHistory(2L, CONV_ID, "assistant", "1234", LocalDateTime.now())
        );
        assertThat(service.estimateTokens(hist)).isEqualTo(1); // only "1234" / 4 = 1
    }

    @Test
    @DisplayName("isSummary returns false when role is not system")
    void isSummary_NonSystemRole_ReturnsFalse() {
        ChatHistory userRow = new ChatHistory(1L, CONV_ID, "user",
                ChatHistoryCompactionService.SUMMARY_MARKER + " foo", LocalDateTime.now());
        // isSummary is private — exercise it via decideCompaction by making history start with a user row
        // Just run maybeCompact with such a list and verify it does NOT treat it as already summarised
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(userRow);
        hist.addAll(buildHistory(12));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        // 13 turns total, first is NOT a summary -> compaction fires
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verify(chatModelResolver).resolve(PROVIDER);
    }

    @Test
    @DisplayName("isSummary returns false when system role content does not start with SUMMARY_MARKER")
    void isSummary_SystemRoleButNoMarker_ReturnsFalse() {
        // system role, non-null content, but not starting with SUMMARY_MARKER
        ChatHistory regularSystem = new ChatHistory(1L, CONV_ID, "system",
                "Regular system message without marker", LocalDateTime.now());
        // Exercise via decideCompaction (first entry is system but not a summary)
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(regularSystem);
        hist.addAll(buildHistory(12));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // isSummary returns false -> alreadySummarised=false -> compaction can proceed
        verify(chatModelResolver).resolve(PROVIDER);
    }

    @Test
    @DisplayName("isSummary returns false when content is null")
    void isSummary_NullContent_ReturnsFalse() {
        ChatHistory nullContent = new ChatHistory(1L, CONV_ID, "system", null, LocalDateTime.now());
        // Similar: exercise through decideCompaction with null-content first entry
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(nullContent);
        hist.addAll(buildHistory(11));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verify(chatModelResolver).resolve(PROVIDER);
    }

    @Test
    @DisplayName("maybeCompact invokes summariser without model when provider has no default model")
    void maybeCompact_ProviderWithNoDefaultModel_InvokesSummariserWithoutModel() {
        // "gemini" is not in providerDefaults -> model = null -> invokeSummariser skips defaultOptions
        historyProperties.getRedis().setEnabled(false);
        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve("gemini")).thenReturn(chatModel);

        ChatResponse noModelResp = buildChatResponseWithContent("[Conversation summary] short summary");
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(noModelResp);

        doAnswer(inv -> {
            Consumer<org.springframework.transaction.TransactionStatus> callback = inv.getArgument(0);
            callback.accept(org.mockito.Mockito.mock(org.springframework.transaction.TransactionStatus.class));
            return null;
        }).when(transactionTemplate).executeWithoutResult(any());

        service.maybeCompact(CONV_ID, "gemini", CompactionOverride.EMPTY);

        verify(chatModelResolver).resolve("gemini");
        verify(transactionTemplate).executeWithoutResult(any());
    }

    @Test
    @DisplayName("invokeSummariser uses provider default model (no override) when model is blank")
    void resolveTarget_ModelFromProviderDefaults_UsedWhenNoOverride() {
        // When override has no model and primary provider has a default, model comes from providerDefaults
        var t = service.resolveTarget(PROVIDER, CompactionOverride.EMPTY);
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget with null override uses primaryProvider and its default model")
    void resolveTarget_NullOverride_UsesPrimaryProvider() {
        // null CompactionOverride -> both null checks short-circuit -> use primaryProvider
        var t = service.resolveTarget(PROVIDER, null);

        assertThat(t.provider()).isEqualTo(PROVIDER);
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget uses default provider model when override has provider only (no model)")
    void resolveTarget_OverrideProviderOnlyUnknownProvider_UsesNullModel() {
        // Override provider set to a provider not in providerDefaults -> model is null
        var t = service.resolveTarget(PROVIDER, new CompactionOverride("unknownprovider", null));
        assertThat(t.provider()).isEqualTo("unknownprovider");
        assertThat(t.model()).isNull();
    }

    @Test
    @DisplayName("applyToPostgres skips deleteAllById when prefix has no IDs")
    void applyToPostgres_EmptyPrefixIds_SkipsDeleteAllById() {
        // We exercise applyToPostgres with prefix having rows with null IDs
        historyProperties.getRedis().setEnabled(false);
        historyProperties.getPostgres().setEnabled(true);

        // Build history where IDs are null -> idsToDelete will be empty
        List<ChatHistory> hist = new ArrayList<>();
        for (int i = 0; i < 12; i++) {
            hist.add(new ChatHistory(null, CONV_ID, "user", "msg " + i, LocalDateTime.now()));
        }
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);

        ChatResponse goodResp = buildChatResponseWithContent("[Conversation summary] valid summary");
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(goodResp);

        doAnswer(inv -> {
            Consumer<org.springframework.transaction.TransactionStatus> callback = inv.getArgument(0);
            callback.accept(org.mockito.Mockito.mock(org.springframework.transaction.TransactionStatus.class));
            return null;
        }).when(transactionTemplate).executeWithoutResult(any());

        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        verify(transactionTemplate).executeWithoutResult(any());
        // deleteAllById should NOT be called because ids are null (filtered out)
        verify(repository, never()).deleteAllById(any());
    }

    // ------------------------------------------------------------------ helpers

    private List<ChatHistory> buildHistory(int turns) {
        List<ChatHistory> hist = new ArrayList<>();
        for (int i = 0; i < turns; i++) {
            hist.add(new ChatHistory((long) (i + 1), CONV_ID,
                    i % 2 == 0 ? "user" : "assistant",
                    "message content " + i,
                    LocalDateTime.now().minusMinutes(turns - i)));
        }
        return hist;
    }

    private ChatHistory summary() {
        return new ChatHistory(0L, CONV_ID, "system",
                ChatHistoryCompactionService.SUMMARY_MARKER + " earlier context here",
                LocalDateTime.now().minusHours(1));
    }

    private ChatResponse buildChatResponseWithContent(String content) {
        AssistantMessage msg = org.mockito.Mockito.mock(AssistantMessage.class);
        when(msg.getText()).thenReturn(content);
        Generation gen = org.mockito.Mockito.mock(Generation.class);
        when(gen.getOutput()).thenReturn(msg);
        ChatResponse resp = org.mockito.Mockito.mock(ChatResponse.class);
        when(resp.getResult()).thenReturn(gen);
        return resp;
    }
}
