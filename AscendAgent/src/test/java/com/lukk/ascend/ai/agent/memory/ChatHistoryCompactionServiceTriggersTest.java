package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import com.lukk.ascend.ai.agent.service.provider.ChatModelResolver;
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

@ExtendWith(MockitoExtension.class)
class ChatHistoryCompactionServiceTriggersTest {

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


    @Test
    @DisplayName("maybeCompact does nothing when only Redis is enabled but history list is empty")
    void maybeCompact_RedisOnlyAndHistoryEmpty_SkipsCompaction() {
        // given — postgres is off, redis is on; repository returns empty since postgres is off
        historyProperties.getPostgres().setEnabled(false);
        historyProperties.getRedis().setEnabled(true);

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verifyNoInteractions(chatModelResolver, transactionTemplate);
    }


    @Test
    @DisplayName("applyToRedis is skipped when Redis is disabled but Postgres is enabled")
    void maybeCompact_PostgresOnlyAndAboveTrigger_AppliesOnlyToPostgres() {
        // given
        historyProperties.getRedis().setEnabled(false);
        historyProperties.getPostgres().setEnabled(true);
        List<ChatHistory> history = buildHistory(15);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("test – provider unavailable"));

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verifyNoInteractions(redisTemplate);
        verify(chatModelResolver).resolve(PROVIDER);
    }


    @Test
    @DisplayName("maybeCompact fires when only token threshold is exceeded (turns below turn trigger)")
    void maybeCompact_TokenTriggered_TriesToInvokeChatModel() {
        // given — 5 turns (below turn-trigger of 10), but very long content -> token-trigger fires
        // Each row has enough characters to push estimated tokens over 50% of lmstudio's 8192 window
        List<ChatHistory> history = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            String bigContent = "x".repeat(20_000); // ~5000 tokens per row, 25000 total >> 4096 threshold
            history.add(new ChatHistory((long) (i + 1), CONV_ID, "user", bigContent, LocalDateTime.now()));
        }
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(anyString())).thenThrow(new IllegalArgumentException("unavailable"));

        // when — use lmstudio as provider (8192 context window) so token trigger fires at 4096 tokens
        service.maybeCompact(CONV_ID, "lmstudio", CompactionOverride.EMPTY);

        // then
        verify(chatModelResolver).resolve(anyString());
    }


    @Test
    @DisplayName("maybeCompact fires when first entry is a summary but remaining turns exceed trigger")
    void maybeCompact_AlreadySummarisedAndRemainingTurnsAboveTrigger_TriesToInvokeChatModel() {
        // given — 1 summary + 12 raw turns: turns-1 = 12 >= trigger(10) -> should proceed
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(summary());
        hist.addAll(buildHistory(12));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verify(chatModelResolver).resolve(PROVIDER);
    }


    @Test
    @DisplayName("maybeCompact skips LLM call when first entry is a summary and turns-1 is below trigger")
    void maybeCompact_AlreadySummarisedAndTurnsMinusOneBelowTrigger_SkipsCompaction() {
        // given — turns = turnTrigger (10), alreadySummarised = true, turns-1 = 9 < 10 -> no compaction
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(summary());
        hist.addAll(buildHistory(9)); // 1 summary + 9 raw = 10 total
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verifyNoInteractions(chatModelResolver);
    }


    @Test
    @DisplayName("computePrefixCount clamps to turns-1 when keepRecentTurns is 0")
    void computePrefixCount_WhenKeepRecentZero_ClampsToTurnsMinusOne() {
        // given
        compactionProperties.setKeepRecentTurns(0);
        service = new ChatHistoryCompactionService(
                compactionProperties, historyProperties, repository,
                redisTemplate, new ObjectMapper(), chatModelResolver,
                aiProviderProperties, transactionTemplate);
        List<ChatHistory> history = buildHistory(12); // 12 turns, keep 0 -> prefixCount = 12 > 12-1=11 => clamp to 11
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("test"));

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then — service still resolves the model (prefixCount=11 >= 1)
        verify(chatModelResolver).resolve(PROVIDER);
    }


    @Test
    @DisplayName("maybeCompact skips persistence when summariser returns null response content")
    void maybeCompact_SummariserReturnsNull_SkipsPersistence() {
        // given
        ChatResponse nullResponse = buildChatResponseWithContent(null);
        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(nullResponse);

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verifyNoInteractions(transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact skips persistence when summariser returns blank response content")
    void maybeCompact_SummariserReturnsBlank_SkipsPersistence() {
        // given
        ChatResponse blankResponse = buildChatResponseWithContent("   ");
        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(blankResponse);

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verifyNoInteractions(transactionTemplate);
    }

    @Test
    @DisplayName("maybeCompact skips persistence when summariser output exceeds hard-cap token count")
    void maybeCompact_SummariserExceedsHardCap_SkipsPersistence() {
        // given — maxSummaryTokens = 400, hardCap = 600 tokens -> 2400 chars; produce a string much longer
        String oversized = "A".repeat(12_000); // ~3000 tokens
        ChatResponse bigResponse = buildChatResponseWithContent("[Conversation summary] " + oversized);
        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(bigResponse);

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verifyNoInteractions(transactionTemplate);
    }


    @Test
    @DisplayName("maybeCompact proceeds to persistence when summariser output is missing the marker (auto-prepend)")
    void maybeCompact_SummariserMissingMarker_AutoPrepends() {
        // given — no [Conversation summary] prefix -> service prepends it and proceeds
        // only postgres, simpler assertions
        historyProperties.getRedis().setEnabled(false);
        ChatResponse markerlessResponse = buildChatResponseWithContent("Short valid summary without marker.");
        List<ChatHistory> history = buildHistory(12);
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(history);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(markerlessResponse);
        doAnswer(inv -> {
            Consumer<org.springframework.transaction.TransactionStatus> callback = inv.getArgument(0);
            callback.accept(org.mockito.Mockito.mock(org.springframework.transaction.TransactionStatus.class));
            return null;
        }).when(transactionTemplate).executeWithoutResult(any());

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verify(transactionTemplate).executeWithoutResult(any());
    }


    @Test
    @DisplayName("resolveTarget falls back to aiProviderProperties.defaultProvider when primaryProvider is blank")
    void resolveTarget_BlankPrimaryProvider_UsesDefaultProvider() {
        // then
        var t = service.resolveTarget("", CompactionOverride.EMPTY);

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget falls back to aiProviderProperties.defaultProvider when primaryProvider is null")
    void resolveTarget_NullPrimaryProvider_UsesDefaultProvider() {
        // then
        var t = service.resolveTarget(null, CompactionOverride.EMPTY);

        assertThat(t.provider()).isEqualTo("openai");
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }


    @Test
    @DisplayName("contextWindow returns 200000 for minimax provider")
    void contextWindow_MinimaxProvider_Returns200k() {
        // then
        assertThat(service.contextWindow("minimax")).isEqualTo(200_000);
    }


    @Test
    @DisplayName("maybeCompact writes to Redis when only Redis is enabled and compaction fires")
    void maybeCompact_RedisEnabledAndAboveTrigger_WritesToRedis() {
        // given
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

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verify(listOperations).trim(anyString(), any(Long.class), any(Long.class));
        verify(listOperations).leftPush(anyString(), anyString());
    }


    @Test
    @DisplayName("maybeCompact skips when prefixCount is 0 (single history entry triggers token threshold)")
    void maybeCompact_SingleEntryTokenTriggered_PrefixCountZeroSkips() {
        // given — keepRecent=5 > 1 turn -> prefixCount=0; very low tokenFraction fires token trigger with 1 entry
        compactionProperties.setKeepRecentTurns(5);
        compactionProperties.setTurnTrigger(100);
        compactionProperties.setTokenTriggerFraction(0.00001);
        service = new ChatHistoryCompactionService(
                compactionProperties, historyProperties, repository,
                redisTemplate, new ObjectMapper(), chatModelResolver,
                aiProviderProperties, transactionTemplate);
        ChatHistory single = new ChatHistory(1L, CONV_ID, "user", "X".repeat(10_000), LocalDateTime.now());
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(List.of(single));

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then — prefixCount = 0 < 1 -> skip (no LLM call)
        verifyNoInteractions(chatModelResolver);
    }


    @Test
    @DisplayName("estimateTokens skips entries with null content")
    void estimateTokens_NullContent_IsSkipped() {
        // given
        List<ChatHistory> hist = List.of(
                new ChatHistory(1L, CONV_ID, "user", null, LocalDateTime.now()),
                new ChatHistory(2L, CONV_ID, "assistant", "1234", LocalDateTime.now())
        );

        // then — only "1234" / 4 = 1
        assertThat(service.estimateTokens(hist)).isEqualTo(1);
    }

    @Test
    @DisplayName("isSummary returns false when role is not system")
    void isSummary_NonSystemRole_ReturnsFalse() {
        // given — isSummary is private; exercise via decideCompaction with history starting with a user row
        ChatHistory userRow = new ChatHistory(1L, CONV_ID, "user",
                ChatHistoryCompactionService.SUMMARY_MARKER + " foo", LocalDateTime.now());
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(userRow);
        hist.addAll(buildHistory(12));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        // when — 13 turns total, first is NOT a summary -> compaction fires
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verify(chatModelResolver).resolve(PROVIDER);
    }

    @Test
    @DisplayName("isSummary returns false when system role content does not start with SUMMARY_MARKER")
    void isSummary_SystemRoleButNoMarker_ReturnsFalse() {
        // given — system role but content does not start with SUMMARY_MARKER
        ChatHistory regularSystem = new ChatHistory(1L, CONV_ID, "system",
                "Regular system message without marker", LocalDateTime.now());
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(regularSystem);
        hist.addAll(buildHistory(12));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then — isSummary returns false -> alreadySummarised=false -> compaction can proceed
        verify(chatModelResolver).resolve(PROVIDER);
    }

    @Test
    @DisplayName("isSummary returns false when content is null")
    void isSummary_NullContent_ReturnsFalse() {
        // given — system role but content is null
        ChatHistory nullContent = new ChatHistory(1L, CONV_ID, "system", null, LocalDateTime.now());
        List<ChatHistory> hist = new ArrayList<>();
        hist.add(nullContent);
        hist.addAll(buildHistory(11));
        when(repository.findAllHistoryOrdered(CONV_ID)).thenReturn(hist);
        when(chatModelResolver.resolve(PROVIDER)).thenThrow(new IllegalArgumentException("unavailable"));

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then
        verify(chatModelResolver).resolve(PROVIDER);
    }

    @Test
    @DisplayName("maybeCompact invokes summariser without model when provider has no default model")
    void maybeCompact_ProviderWithNoDefaultModel_InvokesSummariserWithoutModel() {
        // given — "gemini" is not in providerDefaults -> model = null -> invokeSummariser skips defaultOptions
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

        // when
        service.maybeCompact(CONV_ID, "gemini", CompactionOverride.EMPTY);

        // then
        verify(chatModelResolver).resolve("gemini");
        verify(transactionTemplate).executeWithoutResult(any());
    }

    @Test
    @DisplayName("invokeSummariser uses provider default model (no override) when model is blank")
    void resolveTarget_ModelFromProviderDefaults_UsedWhenNoOverride() {
        // then
        var t = service.resolveTarget(PROVIDER, CompactionOverride.EMPTY);
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget with null override uses primaryProvider and its default model")
    void resolveTarget_NullOverride_UsesPrimaryProvider() {
        // then
        var t = service.resolveTarget(PROVIDER, null);

        assertThat(t.provider()).isEqualTo(PROVIDER);
        assertThat(t.model()).isEqualTo("gpt-4o-mini");
    }

    @Test
    @DisplayName("resolveTarget uses default provider model when override has provider only (no model)")
    void resolveTarget_OverrideProviderOnlyUnknownProvider_UsesNullModel() {
        // then — override provider not in providerDefaults -> model is null
        var t = service.resolveTarget(PROVIDER, new CompactionOverride("unknownprovider", null));
        assertThat(t.provider()).isEqualTo("unknownprovider");
        assertThat(t.model()).isNull();
    }

    @Test
    @DisplayName("applyToPostgres skips deleteAllById when prefix has no IDs")
    void applyToPostgres_EmptyPrefixIds_SkipsDeleteAllById() {
        // given — prefix rows have null IDs -> idsToDelete will be empty
        historyProperties.getRedis().setEnabled(false);
        historyProperties.getPostgres().setEnabled(true);
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

        // when
        service.maybeCompact(CONV_ID, PROVIDER, CompactionOverride.EMPTY);

        // then — deleteAllById should NOT be called because ids are null (filtered out)
        verify(transactionTemplate).executeWithoutResult(any());
        verify(repository, never()).deleteAllById(any());
    }


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
