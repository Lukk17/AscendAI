package com.lukk.ascend.ai.orchestrator.exception;

public class UnsupportedFileTypeException extends RuntimeException {
    public UnsupportedFileTypeException(String extension) {
        super("Filetype is not supported: " + extension);
    }
}
