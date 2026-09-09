package com.lukk.ascend.ai.agent.exception;

public class UnsupportedFileTypeException extends RuntimeException {
    public UnsupportedFileTypeException(String extension) {
        super("Filetype is not supported: " + extension);
    }
}
