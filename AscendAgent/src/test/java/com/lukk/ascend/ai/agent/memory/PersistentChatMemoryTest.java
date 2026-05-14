package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.exception.ServiceException;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PersistentChatMemoryTest {

    private static final String DEFAULT_CONVERSATION_ID = "convo-123";
    private static final String REDIS_KEY = "chat:convo-123";

    @Mock
    private ChatHistoryRepository repository;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ListOperations<String, String> listOperations;

    private PersistentChatMemory persistentChatMemory;

    @BeforeEach
    void setup() {
        ChatHistoryProperties properties = new ChatHistoryProperties();
        properties.setMaxSize(5);
        persistentChatMemory = new PersistentChatMemory(repository, redisTemplate, new ObjectMapper(), properties);
    }

    @Test
    void get_WhenInRedis_ThenReturnsFromRedisAndIgnoresDB() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(List.of(
                "{\"role\":\"user\",\"content\":\"Hello\"}",
                "{\"role\":\"assistant\",\"content\":\"Hi there\"}"));

        List<Message> result = persistentChatMemory.get(DEFAULT_CONVERSATION_ID, 10);

        assertThat(result).hasSize(2);
        assertThat(result.get(0)).isInstanceOf(UserMessage.class);
        assertThat(result.get(0).getText()).isEqualTo("Hello");
        assertThat(result.get(1)).isInstanceOf(AssistantMessage.class);
        assertThat(result.get(1).getText()).isEqualTo("Hi there");
    }

    @Test
    void get_WhenNotInRedis_ThenReturnsFromPostgresAndCachesToRedis() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(List.of());

        ChatHistory historyRow = new ChatHistory(1L, DEFAULT_CONVERSATION_ID, "user", "DB Hello", LocalDateTime.now());
        when(repository.findRecentHistory(DEFAULT_CONVERSATION_ID, 5)).thenReturn(List.of(historyRow));

        List<Message> result = persistentChatMemory.get(DEFAULT_CONVERSATION_ID, 10);

        assertThat(result).hasSize(1);
        assertThat(result.get(0).getText()).isEqualTo("DB Hello");

        verify(listOperations).rightPushAll(eq(REDIS_KEY), eq(List.of("{\"role\":\"user\",\"content\":\"DB Hello\"}")));
    }

    @Test
    void add_WhenInvoked_ThenPushesToRedisAndPersistsToDBAsync() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        persistentChatMemory.add(DEFAULT_CONVERSATION_ID, List.of(new UserMessage("Save me")));

        verify(listOperations).rightPush(REDIS_KEY, "{\"role\":\"user\",\"content\":\"Save me\"}");
        verify(listOperations).trim(REDIS_KEY, 0, 4);
        verify(repository).save(any(ChatHistory.class));
    }

    @Test
    void get_WhenThrowsException_ThenWrapsInServiceException() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(anyString(), eq(0L), eq(-1L))).thenThrow(new RuntimeException("Redis timeout"));

        assertThatThrownBy(() -> persistentChatMemory.get(DEFAULT_CONVERSATION_ID))
                .isInstanceOf(ServiceException.class)
                .hasMessageContaining("Failed to retrieve chat memory");
    }

    @Test
    void clear_WhenInvoked_ThenDeletesRedisKey() {
        persistentChatMemory.clear(DEFAULT_CONVERSATION_ID);

        verify(redisTemplate).delete(REDIS_KEY);
    }
}
