package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.ServiceException;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
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

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private PersistentChatMemory memory;

    @BeforeEach
    void setup() {
        ReflectionTestUtils.setField(memory, "maxSize", 5);
        ReflectionTestUtils.setField(memory, "ttl", Duration.ofHours(24));
    }

    @Test
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
    void get_WhenUnknownRole_ThenFallsBackToUserMessage() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1))
                .thenReturn(List.of("{\"role\":\"weird\",\"content\":\"meh\"}"));

        List<Message> result = memory.get(CONVO_ID, 5);

        assertThat(result).hasSize(1);
        assertThat(result.get(0)).isInstanceOf(UserMessage.class);
        assertThat(result.get(0).getText()).isEqualTo("meh");
    }

    @Test
    void add_AppliesTtlOnRedisKeyAfterPush() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        memory.add(CONVO_ID, List.of(new UserMessage("hello")));

        verify(listOperations).rightPush(eq(REDIS_KEY), any());
        verify(redisTemplate).expire(eq(REDIS_KEY), eq(Duration.ofHours(24)));
    }

    @Test
    void getFromPostgres_AppliesTtlOnRedisCachePopulation() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(listOperations.range(REDIS_KEY, 0, -1)).thenReturn(List.of());

        com.lukk.ascend.ai.agent.model.ChatHistory row = new com.lukk.ascend.ai.agent.model.ChatHistory(
                1L, CONVO_ID, "user", "from-db", java.time.LocalDateTime.now());
        when(repository.findRecentHistory(CONVO_ID, 5)).thenReturn(List.of(row));

        memory.get(CONVO_ID, 10);

        verify(listOperations).rightPushAll(eq(REDIS_KEY), any(List.class));
        verify(redisTemplate).expire(eq(REDIS_KEY), eq(Duration.ofHours(24)));
    }

    @Test
    void add_WhenRedisThrows_ThenWrapsInServiceException() {
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        doThrow(new RuntimeException("redis down"))
                .when(listOperations).rightPush(eq(REDIS_KEY), any());

        assertThatThrownBy(() -> memory.add(CONVO_ID, List.of(new UserMessage("x"))))
                .isInstanceOf(ServiceException.class)
                .hasMessageContaining("Failed to add to chat memory");
    }

    @Test
    void persistToDb_SwallowsRepositoryFailure() {
        doThrow(new RuntimeException("db down")).when(repository).save(any());

        // Should not throw — async helper logs and swallows.
        memory.persistToDb(CONVO_ID, new UserMessage("text"));
    }
}
