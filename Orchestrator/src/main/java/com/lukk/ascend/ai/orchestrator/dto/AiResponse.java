package com.lukk.ascend.ai.orchestrator.dto;

import org.springframework.ai.chat.metadata.ChatResponseMetadata;

public record AiResponse(String content, ChatResponseMetadata metadata) {
}

