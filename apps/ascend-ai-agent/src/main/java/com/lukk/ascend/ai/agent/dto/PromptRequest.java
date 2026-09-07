package com.lukk.ascend.ai.agent.dto;

public record PromptRequest(
        String prompt,
        String imageUrl,
        String documentUrl) {
}
