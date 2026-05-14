package com.lukk.ascend.ai.agent.service.rag;

public record SourceRef(String bucket, String key, String displayName, String mimeType) {

    public String s3Uri() {
        return "s3://" + bucket + "/" + key;
    }
}
