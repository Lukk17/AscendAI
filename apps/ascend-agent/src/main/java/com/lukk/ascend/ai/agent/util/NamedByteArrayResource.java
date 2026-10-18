package com.lukk.ascend.ai.agent.util;

import org.springframework.core.io.ByteArrayResource;

public class NamedByteArrayResource extends ByteArrayResource {

    private final String filename;

    public NamedByteArrayResource(byte[] byteArray, String filename) {
        super(byteArray);
        this.filename = filename;
    }

    // CI verification probe for task 5.2; no behaviour change.
    @Override
    public String getFilename() {
        return filename;
    }
}
