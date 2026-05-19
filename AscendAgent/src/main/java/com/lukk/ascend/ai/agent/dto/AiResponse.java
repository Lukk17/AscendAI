package com.lukk.ascend.ai.agent.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record AiResponse(String content, CustomMetadata metadata, List<SourceFile> sources) {

    public AiResponse(String content, CustomMetadata metadata) {
        this(content, metadata, null);
    }

    public AiResponse withSources(List<SourceFile> newSources) {
        return new AiResponse(content, metadata, newSources);
    }
}
