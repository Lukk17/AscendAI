package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.exception.ServiceException;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PersistentChatMemoryExtraTest {

    private static final String CONVO_ID = "convo-x";
    private static final String REDIS_KEY = "chat:convo-x";

    @Mock
    private ChatHistoryRepository repository;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ListOperations<String, String> listOperations;

    private ChatHistoryProperties properties;
    private com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties compactionProperties;
    private com.lukk.ascend.ai.agent.memory.ChatHistoryCompactionService compactionService;
    private PersistentChatMemory memory;

    @BeforeEach
    void setup() {
        properties = new ChatHistoryProperties();
        properties.setMaxSize(5);
        properties.setTtl(Duration.ofHours(24));
        compactionProperties = new com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties();
        compactionProperties.setEnabled(false);
        compactionService = org.mockito.Mockito.mock(com.lukk.ascend.ai.agent.memory.ChatHistoryCompactionService.class);
        memory = new PersistentChatMemory(repository, redisTemplate, new ObjectMapper(),
                properties, compactionProperties, compactionService);
    }

    @Test
    @DisplayName("get with no limit delegates to overload and returns all messages")
    void getNoLimit_DelegatesToOverloadWithMaxSize() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1))
                .thenReturn(List.of(
                        "{\"role\":\"user\",\"content\":\"hi\"}",
                        "{\"role\":\"assistant\",\"content\":\"hello\"}",
                        "{\"role\":\"system\",\"content\":\"sys\"}"));

        List<Message> result = memory.get(CONVO_ID);

        assertThat(result).hasSize(3);
        assertThat(result.get(0)).isInstanceOf(UserMessage.class);
        assertThat(result.get(1)).isInstanceOf(AssistantMessage.class);
        assertThat(result.get(2)).isInstanceOf(SystemMessage.class);
    }

    @Test
    @DisplayName("get falls back to UserMessage when message role is unrecognized")
    void get_WhenUnknownRole_ThenFallsBackToUserMessage() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1))
                .thenReturn(List.of("{\"role\":\"weird\",\"content\":\"meh\"}"));

        List<Message> result = memory.get(CONVO_ID, 5);

        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).isInstanceOf(UserMessage.class);
        assertThat(result.getFirst().getText()).isEqualTo("meh");
    }

    @Test
    @DisplayName("add sets TTL on the Redis key after pushing the message")
    void add_AppliesTtlOnRedisKeyAfterPush() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        memory.add(CONVO_ID, List.of(new UserMessage("hello")));

        verify(listOperations).rightPush(eq(REDIS_KEY), any());
        verify(redisTemplate).expire(eq(REDIS_KEY), eq(Duration.ofHours(24)));
    }

    @Test
    @DisplayName("get sets TTL on Redis key when populating cache from Postgres")
    void getFromPostgres_AppliesTtlOnRedisCachePopulation() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(List.of());

        com.lukk.ascend.ai.agent.model.ChatHistory row = new com.lukk.ascend.ai.agent.model.ChatHistory(
                1L, CONVO_ID, "user", "from-db", java.time.LocalDateTime.now());
        when(repository.findRecentHistory(CONVO_ID, 5)).thenReturn(List.of(row));

        memory.get(CONVO_ID, 10);

        verify(listOperations).rightPushAll(eq(REDIS_KEY), org.mockito.ArgumentMatchers.<java.util.Collection<String>>any());
        verify(redisTemplate).expire(eq(REDIS_KEY), eq(Duration.ofHours(24)));
    }

    @Test
    @DisplayName("add wraps Redis exception in ServiceException")
    void add_WhenRedisThrows_ThenWrapsInServiceException() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        doThrow(new RuntimeException("redis down"))
                .when(listOperations).rightPush(eq(REDIS_KEY), any());

        assertThatThrownBy(() -> memory.add(CONVO_ID, List.of(new UserMessage("x"))))
                .isInstanceOf(ServiceException.class)
                .hasMessageContaining("Failed to add to chat memory");
    }

    @Test
    @DisplayName("persistToDb swallows repository failures silently")
    void persistToDb_SwallowsRepositoryFailure() {
        doThrow(new RuntimeException("db down")).when(repository).save(any());

        memory.persistToDb(CONVO_ID, new UserMessage("text"));
    }

    @ParameterizedTest(name = "get redis={0} postgres={1}")
    @CsvSource({
            "true,  true",
            "true,  false",
            "false, true",
            "false, false"
    })
    void get_RespectsBackendToggles_ForAllFourCombinations(boolean redisOn, boolean postgresOn) {
        properties.getRedis().setEnabled(redisOn);
        properties.getPostgres().setEnabled(postgresOn);

        if (redisOn) {
            lenient().when(redisTemplate.opsForList()).thenReturn(listOperations);
            lenient().when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(List.of());
        }
        if (postgresOn) {
            com.lukk.ascend.ai.agent.model.ChatHistory row = new com.lukk.ascend.ai.agent.model.ChatHistory(
                    1L, CONVO_ID, "user", "from-db", java.time.LocalDateTime.now());
            lenient().when(repository.findRecentHistory(CONVO_ID, 5)).thenReturn(List.of(row));
        }

        List<Message> result = memory.get(CONVO_ID, 10);

        if (!redisOn && !postgresOn) {
            assertThat(result).isEmpty();
            verifyNoInteractions(redisTemplate);
            verifyNoInteractions(repository);
            return;
        }
        if (!redisOn) {
            verify(redisTemplate, never()).opsForList();
            verify(repository).findRecentHistory(CONVO_ID, 5);
            assertThat(result).hasSize(1);
            return;
        }
        if (!postgresOn) {
            verify(repository, never()).findRecentHistory(eq(CONVO_ID), eq(5));
            assertThat(result).isEmpty();
            return;
        }
        verify(repository).findRecentHistory(CONVO_ID, 5);
    }

    @ParameterizedTest(name = "add redis={0} postgres={1}")
    @CsvSource({
            "true,  true",
            "true,  false",
            "false, true",
            "false, false"
    })
    void add_RespectsBackendToggles_ForAllFourCombinations(boolean redisOn, boolean postgresOn) {
        properties.getRedis().setEnabled(redisOn);
        properties.getPostgres().setEnabled(postgresOn);
        if (redisOn) {
            when(redisTemplate.opsForList()).thenReturn(listOperations);
        }

        memory.add(CONVO_ID, List.of(new UserMessage("hello")));

        if (redisOn) {
            verify(listOperations).rightPush(eq(REDIS_KEY), any());
            verify(listOperations).trim(REDIS_KEY, 0, 4);
            verify(redisTemplate).expire(eq(REDIS_KEY), eq(Duration.ofHours(24)));
        } else {
            verifyNoInteractions(redisTemplate);
        }
        if (postgresOn) {
            verify(repository).save(any());
        } else {
            verify(repository, never()).save(any());
        }
    }

    @Test
    @DisplayName("add calls maybeCompact with the supplied provider and override after persisting")
    void add_InvokesMaybeCompactAfterPersistence() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        memory.add(CONVO_ID, List.of(new UserMessage("hello")), "anthropic", new CompactionOverride("openai", "gpt-4o-mini"));

        verify(compactionService).maybeCompact(eq(CONVO_ID), eq("anthropic"), eq(new CompactionOverride("openai", "gpt-4o-mini")));
    }

    @Test
    @DisplayName("add swallows compaction exceptions so the user turn is never broken")
    void add_WhenMaybeCompactThrows_ExceptionIsSwallowed() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        doThrow(new RuntimeException("compaction blew up"))
                .when(compactionService).maybeCompact(any(), any(), any());

        // Must not throw — compaction failures never break the user's turn.
        memory.add(CONVO_ID, List.of(new UserMessage("hi")));
    }

    @Test
    @DisplayName("two-argument add delegates to four-argument overload with null provider and EMPTY override")
    void add_TwoArgOverload_DelegatesToFourArgWithNullProviderAndEmptyOverride() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        memory.add(CONVO_ID, List.of(new UserMessage("hi")));

        verify(compactionService).maybeCompact(eq(CONVO_ID), eq(null), eq(CompactionOverride.EMPTY));
    }

    @Test
    @DisplayName("add trims Redis list to the larger of maxSize and keepRecentTurns+1 when compaction is enabled")
    void add_RedisTrim_UsesEffectiveCacheSizeWhenCompactionEnabled() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        compactionProperties.setEnabled(true);
        compactionProperties.setKeepRecentTurns(8);
        properties.setMaxSize(5);

        memory.add(CONVO_ID, List.of(new UserMessage("hello")));

        // effective = max(5, 8 + 1) = 9 → trim to 0..8
        verify(listOperations).trim(REDIS_KEY, 0, 8);
    }

    @Test
    @DisplayName("clear always attempts Redis delete even when the Redis backend is disabled")
    void clear_AlwaysAttemptsRedisDelete_EvenWhenRedisDisabled() {
        properties.getRedis().setEnabled(false);
        properties.getPostgres().setEnabled(false);

        memory.clear(CONVO_ID);

        verify(redisTemplate).delete(REDIS_KEY);
    }
}
