package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.model.UserInstruction;
import com.lukk.ascend.ai.orchestrator.repository.UserInstructionRepository;
import com.lukk.ascend.ai.orchestrator.exception.ServiceException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class UserInstructionServiceTest {

    private static final String DEFAULT_USER_ID = "user1";
    private static final String CACHE_KEY = "user:user1:instructions";
    private static final String INSTRUCTION_TEXT = "Be very concise";
    private static final String EMPTY_MARKER = "EMPTY";
    private static final Duration TTL = Duration.ofDays(1);

    @Mock
    private UserInstructionRepository repository;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ValueOperations<String, String> valueOperations;

    @InjectMocks
    private UserInstructionService userInstructionService;

    @BeforeEach
    void setupGlobalFields() {
        ReflectionTestUtils.setField(userInstructionService, "cacheTtl", TTL);
    }

    @Test
    void getInstructions_WhenCachedInRedis_ThenReturnsCachedValue() {
        // given
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get(CACHE_KEY)).thenReturn(INSTRUCTION_TEXT);

        // when
        String result = userInstructionService.getInstructions(DEFAULT_USER_ID);

        // then
        assertThat(result).isEqualTo(INSTRUCTION_TEXT);
    }

    @Test
    void getInstructions_WhenRedisEmptyMarker_ThenReturnsEmptyString() {
        // given
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get(CACHE_KEY)).thenReturn(EMPTY_MARKER);

        // when
        String result = userInstructionService.getInstructions(DEFAULT_USER_ID);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void getInstructions_WhenNotInRedisButInDb_ThenCachesAndReturnsFromDb() {
        // given
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get(CACHE_KEY)).thenReturn(null);
        
        UserInstruction entity = new UserInstruction(DEFAULT_USER_ID, INSTRUCTION_TEXT, LocalDateTime.now());
        when(repository.findById(DEFAULT_USER_ID)).thenReturn(Optional.of(entity));

        // when
        String result = userInstructionService.getInstructions(DEFAULT_USER_ID);

        // then
        assertThat(result).isEqualTo(INSTRUCTION_TEXT);
        verify(valueOperations).set(CACHE_KEY, INSTRUCTION_TEXT, TTL);
    }

    @Test
    void getInstructions_WhenNotInRedisAndNotInDb_ThenCachesEmptyMarkerAndReturnsEmptyString() {
        // given
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get(CACHE_KEY)).thenReturn(null);
        when(repository.findById(DEFAULT_USER_ID)).thenReturn(Optional.empty());

        // when
        String result = userInstructionService.getInstructions(DEFAULT_USER_ID);

        // then
        assertThat(result).isEmpty();
        verify(valueOperations).set(CACHE_KEY, EMPTY_MARKER, TTL);
    }

    @Test
    void getInstructions_WhenRedisThrowsException_ThenThrowsServiceException() {
        // given
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get(anyString())).thenThrow(new RuntimeException("Redis disconnected"));

        // when / then
        assertThatThrownBy(() -> userInstructionService.getInstructions(DEFAULT_USER_ID))
                .isInstanceOf(ServiceException.class)
                .hasMessageContaining("Failed to fetch user instructions");
    }

    @Test
    void updateInstructions_WhenInvoked_ThenSavesToDbAndDeletesRedisKey() {
        // when
        userInstructionService.updateInstructions(DEFAULT_USER_ID, INSTRUCTION_TEXT);

        // then
        verify(repository).save(any(UserInstruction.class));
        verify(redisTemplate).delete(CACHE_KEY);
    }

    @Test
    void updateInstructions_WhenDbFails_ThenThrowsServiceException() {
        // given
        doThrow(new RuntimeException("DB offline")).when(repository).save(any(UserInstruction.class));

        // when / then
        assertThatThrownBy(() -> userInstructionService.updateInstructions(DEFAULT_USER_ID, INSTRUCTION_TEXT))
                .isInstanceOf(ServiceException.class)
                .hasMessageContaining("Failed to update user instructions");
    }
}
