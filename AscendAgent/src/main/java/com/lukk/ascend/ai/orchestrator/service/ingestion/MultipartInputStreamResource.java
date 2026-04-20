package com.lukk.ascend.ai.orchestrator.service.ingestion;

import lombok.EqualsAndHashCode;
import org.springframework.core.io.InputStreamResource;

import java.io.IOException;
import java.io.InputStream;

@EqualsAndHashCode(callSuper = true)
public class MultipartInputStreamResource extends InputStreamResource {
    private final String filename;

    public MultipartInputStreamResource(InputStream inputStream, String filename) {
        super(inputStream);
        this.filename = filename;
    }

    @Override
    public String getFilename() {
        return this.filename;
    }

    @Override
    public long contentLength() {
        try {
            return getInputStream().available();
        } catch (IOException e) {
            return -1;
        }
    }
}
