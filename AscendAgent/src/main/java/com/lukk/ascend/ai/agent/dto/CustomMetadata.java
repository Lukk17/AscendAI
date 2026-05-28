package com.lukk.ascend.ai.agent.dto;

import com.fasterxml.jackson.annotation.JsonUnwrapped;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;

import java.util.List;

@RequiredArgsConstructor
@EqualsAndHashCode
@Getter
public class CustomMetadata {

    @JsonUnwrapped
    private final ChatResponseMetadata delegate;
    private final List<String> toolsUsed;
}
