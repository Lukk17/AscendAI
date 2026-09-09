package com.lukk.ascend.ai.agent.dto;

import com.fasterxml.jackson.annotation.JsonUnwrapped;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;

import java.util.List;

public record CustomMetadata(
        @JsonUnwrapped ChatResponseMetadata delegate,
        List<String> toolsUsed
) {
}
