package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.exception.ServiceException;
import com.lukk.ascend.ai.orchestrator.model.UserInstruction;
import com.lukk.ascend.ai.orchestrator.repository.UserInstructionRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class UserInstructionService {

    private final UserInstructionRepository repository;
    private final StringRedisTemplate redisTemplate;

    @Value("${app.memory.user-profile.ttl}")
    private Duration cacheTtl;

    private static final String EMPTY_MARKER = "EMPTY";

    public String getInstructions(String userId) {
        String key = "user:" + userId + ":instructions";
        try {
            String cached = redisTemplate.opsForValue().get(key);
            if (cached != null) {
                log.info("Instructions retrieved from: REDIS for user: {}", userId);
                return EMPTY_MARKER.equals(cached) ? "" : cached;
            }

            Optional<UserInstruction> instruction = repository.findById(userId);

            if (instruction.isPresent()) {
                String text = instruction.get().getInstructionText();
                redisTemplate.opsForValue().set(key, text, cacheTtl);
                log.info("Instructions retrieved from: DB for user: {}", userId);
                return text;
            } else {
                redisTemplate.opsForValue().set(key, EMPTY_MARKER, cacheTtl);
                log.info("Instructions retrieved from: DB (Empty) for user: {}", userId);
                return "";
            }

        } catch (Exception e) {
            log.error("Failed to fetch user instructions for user: {}", userId, e);
            throw new ServiceException("Failed to fetch user instructions", e);
        }
    }

    @Transactional
    public void updateInstructions(String userId, String text) {
        String key = "user:" + userId + ":instructions";
        try {
            UserInstruction entity = new UserInstruction(userId, text, LocalDateTime.now());
            repository.save(entity);

            redisTemplate.delete(key);
            log.info("User instructions updated for user: {}", userId);
        } catch (Exception e) {
            log.error("Failed to update user instructions for user: {}", userId, e);
            throw new ServiceException("Failed to update user instructions", e);
        }
    }
}
