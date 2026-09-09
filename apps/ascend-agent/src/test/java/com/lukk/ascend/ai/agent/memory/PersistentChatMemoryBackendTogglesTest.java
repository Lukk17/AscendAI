package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PersistentChatMemoryBackendTogglesTest {

    private static final String CONV_ID = "convo-extra";
    private static final String REDIS_KEY = "chat:convo-extra";

    @Mock
    private ChatHistoryRepository repository;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ListOperations<String, String> listOperations;

    @Mock
    private ChatHistoryCompactionService compactionService;

    private ChatHistoryProperties properties;
    private ChatHistoryCompactionProperties compactionProperties;

    private PersistentChatMemory memory;

    @BeforeEach
    void setUp() {
        properties = new ChatHistoryProperties();
        properties.setMaxSize(5);

        compactionProperties = new ChatHistoryCompactionProperties();
        compactionProperties.setEnabled(false);

        memory = new PersistentChatMemory(repository, redisTemplate, new ObjectMapper(),
                properties, compactionProperties, compactionService);
    }


    @Test
    @DisplayName("get returns empty list when both Redis and Postgres are disabled")
    void get_BothBackendsDisabled_ReturnsEmpty() {
        // given
        properties.getRedis().setEnabled(false);
        properties.getPostgres().setEnabled(false);
        recreateMemory();

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("add does nothing when both Redis and Postgres are disabled")
    void add_BothBackendsDisabled_DoesNothing() {
        // given
        properties.getRedis().setEnabled(false);
        properties.getPostgres().setEnabled(false);
        recreateMemory();

        // then
        memory.add(CONV_ID, List.of(new UserMessage("hello")));
    }


    @Test
    @DisplayName("get loads from Postgres only when Redis is disabled")
    void get_RedisDisabledPostgresEnabled_LoadsFromPostgresOnly() {
        // given
        properties.getRedis().setEnabled(false);
        properties.getPostgres().setEnabled(true);
        recreateMemory();
        ChatHistory row = new ChatHistory(1L, CONV_ID, "user", "Hello from DB", LocalDateTime.now());
        when(repository.findRecentHistory(CONV_ID, 5)).thenReturn(List.of(row));

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getText()).isEqualTo("Hello from DB");
    }

    @Test
    @DisplayName("get returns empty list when Redis is disabled and Postgres returns nothing")
    void get_RedisDisabledPostgresEmpty_ReturnsEmpty() {
        // given
        properties.getRedis().setEnabled(false);
        properties.getPostgres().setEnabled(true);
        recreateMemory();
        when(repository.findRecentHistory(CONV_ID, 5)).thenReturn(Collections.emptyList());

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).isEmpty();
    }


    @Test
    @DisplayName("get maps 'system' role from Redis to SystemMessage")
    void get_SystemRoleFromRedis_MapsToSystemMessage() {
        // given
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1))
                .thenReturn(List.of("{\"role\":\"system\",\"content\":\"You are a helpful assistant.\"}"));

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).isInstanceOf(SystemMessage.class);
    }

    @Test
    @DisplayName("get maps 'assistant' role from Redis to AssistantMessage")
    void get_AssistantRoleFromRedis_MapsToAssistantMessage() {
        // given
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1))
                .thenReturn(List.of("{\"role\":\"assistant\",\"content\":\"Hello!\"}"));

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).isInstanceOf(AssistantMessage.class);
    }

    @Test
    @DisplayName("get maps unknown role from Redis to UserMessage (fallback)")
    void get_UnknownRoleFromRedis_FallsBackToUserMessage() {
        // given
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1))
                .thenReturn(List.of("{\"role\":\"unknown_role\",\"content\":\"Strange message.\"}"));

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).isInstanceOf(UserMessage.class);
    }


    @Test
    @DisplayName("add trims Redis cache to keepRecentTurns+1 when compaction is enabled and keepRecentTurns > maxSize")
    void add_CompactionEnabledWithLargeKeepRecent_TrimsToCompactionSize() {
        // given
        compactionProperties.setEnabled(true);
        compactionProperties.setKeepRecentTurns(10); // > maxSize(5) -> effectiveCacheSize = 11
        properties.setMaxSize(5);
        recreateMemory();
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        // then
        memory.add(CONV_ID, List.of(new UserMessage("message")));
    }

    @Test
    @DisplayName("get slices to lastN when Redis has more messages than requested")
    void get_MoreMessagesThanLastN_SlicesToLastN() {
        // given
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(List.of(
                "{\"role\":\"user\",\"content\":\"msg1\"}",
                "{\"role\":\"user\",\"content\":\"msg2\"}",
                "{\"role\":\"user\",\"content\":\"msg3\"}",
                "{\"role\":\"user\",\"content\":\"msg4\"}",
                "{\"role\":\"user\",\"content\":\"msg5\"}"
        ));

        // when — request only last 2
        List<Message> result = memory.get(CONV_ID, 2);

        // then
        assertThat(result).hasSize(2);
        assertThat(result.getFirst().getText()).isEqualTo("msg4");
        assertThat(result.get(1).getText()).isEqualTo("msg5");
    }


    @Test
    @DisplayName("logToggleState logs Enabled/Enabled when both backends are on and compaction is on")
    void logToggleState_BothEnabledAndCompactionEnabled_LogsEnabled() {
        // given
        properties.getRedis().setEnabled(true);
        properties.getPostgres().setEnabled(true);
        compactionProperties.setEnabled(true);
        recreateMemory();

        // then
        memory.logToggleState();
    }

    @Test
    @DisplayName("logToggleState logs Disabled for Redis when Redis is disabled")
    void logToggleState_RedisDisabled_LogsRedisDisabled() {
        // given
        properties.getRedis().setEnabled(false);
        properties.getPostgres().setEnabled(true);
        compactionProperties.setEnabled(false);
        recreateMemory();

        // then
        memory.logToggleState();
    }

    @Test
    @DisplayName("logToggleState logs Disabled for Postgres when Postgres is disabled")
    void logToggleState_PostgresDisabled_LogsPostgresDisabled() {
        // given
        properties.getRedis().setEnabled(true);
        properties.getPostgres().setEnabled(false);
        compactionProperties.setEnabled(true);
        recreateMemory();

        // then
        memory.logToggleState();
    }


    @Test
    @DisplayName("get returns empty list when Redis opsForList.range returns null")
    void get_RedisRangeReturnsNull_LoadsFromPostgres() {
        // given
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(null);
        when(repository.findRecentHistory(CONV_ID, 5)).thenReturn(List.of());

        // when
        List<Message> result = memory.get(CONV_ID, 10);

        // then
        assertThat(result).isEmpty();
    }


    private void recreateMemory() {
        memory = new PersistentChatMemory(repository, redisTemplate, new ObjectMapper(),
                properties, compactionProperties, compactionService);
    }
}
