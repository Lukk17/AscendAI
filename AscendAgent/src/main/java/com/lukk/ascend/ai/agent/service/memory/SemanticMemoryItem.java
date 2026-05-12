package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.annotation.JsonAlias;

import java.time.Instant;
import java.util.Map;

public record SemanticMemoryItem(
        String id,
        @JsonAlias("user_id") String userId,
        @JsonAlias("memory") String text,
        double score,
        @JsonAlias("created_at") Instant createdAt,
        Map<String, String> metadata) {
}
