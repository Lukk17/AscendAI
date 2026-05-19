package com.lukk.ascend.ai.agent.service.rag;

import java.util.List;

public record RagRetrievalResult(String context, List<SourceRef> sources, boolean retrievalRan) {

    public static RagRetrievalResult skipped() {
        return new RagRetrievalResult("", List.of(), false);
    }

    public static RagRetrievalResult empty() {
        return new RagRetrievalResult("", List.of(), true);
    }
}
