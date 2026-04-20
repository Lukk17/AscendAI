package com.lukk.ascend.ai.agent.service.memory;

import java.time.Instant;
import java.util.Map;

public record SemanticMemoryItem(
        String id,
        String userId,
        String text,
        double score,
        Instant createdAt,
        Map<String, String> metadata) {
}

