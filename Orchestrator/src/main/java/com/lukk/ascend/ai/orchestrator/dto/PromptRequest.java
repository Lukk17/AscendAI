package com.lukk.ascend.ai.orchestrator.dto;

public record PromptRequest(
                String prompt,
                String imageUrl,
                String documentUrl) {
}
