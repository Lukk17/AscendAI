package com.lukk.ascend.ai.orchestrator.exception;

public class IncompatibleEmbeddingException extends RuntimeException {

    public IncompatibleEmbeddingException(String chatProvider, String embeddingProvider,
                                          int embeddingDimensions, int requiredDimensions) {
        super(buildMessage(chatProvider, embeddingProvider, embeddingDimensions, requiredDimensions));
    }

    private static String buildMessage(String chatProvider, String embeddingProvider,
                                       int embeddingDimensions, int requiredDimensions) {
        return "Chat provider '%s' is incompatible with embedding provider '%s' (%d-dim). "
                .formatted(chatProvider, embeddingProvider, embeddingDimensions)
                + "Expected %d-dim embeddings. ".formatted(requiredDimensions)
                + "Set EMBEDDING_PROVIDER to a compatible provider or choose a different chat provider.";
    }
}
