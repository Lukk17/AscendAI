package com.lukk.ascend.ai.agent.exception;

public class AiGenerationException extends RuntimeException {
    public AiGenerationException(String message) {
        super(message);
    }

    public AiGenerationException(String message, Throwable cause) {
        super(message, cause);
    }
}
