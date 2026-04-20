package com.lukk.ascend.ai.agent.exception;

public class DocumentRoutingException extends RuntimeException {
    public DocumentRoutingException(String message) {
        super(message);
    }

    public DocumentRoutingException(String message, Throwable cause) {
        super(message, cause);
    }
}
