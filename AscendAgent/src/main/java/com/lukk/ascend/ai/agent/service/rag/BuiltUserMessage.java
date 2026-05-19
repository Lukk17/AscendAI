package com.lukk.ascend.ai.agent.service.rag;

import java.util.List;

public record BuiltUserMessage(String text, List<SourceRef> sources, boolean ragRetrievalRan) {

    public static BuiltUserMessage textOnly(String text) {
        return new BuiltUserMessage(text, List.of(), false);
    }
}
