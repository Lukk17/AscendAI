package com.lukk.ai.orchestrator.dto;

import com.fasterxml.jackson.annotation.JsonUnwrapped;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;

import java.util.List;

@RequiredArgsConstructor
@EqualsAndHashCode(callSuper = true)
@Getter
public class CustomMetadata extends ChatResponseMetadata {

    @JsonUnwrapped
    private final ChatResponseMetadata delegate;
    private final List<String> toolsUsed;
}
