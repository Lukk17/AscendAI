package com.lukk.ascend.ai.orchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.io.IOException;
import java.io.InputStream;

@Service
@RequiredArgsConstructor
@Slf4j
public class StorageService {

    private final S3Client s3Client;

    @Value("${app.s3.bucket:knowledge-base}")
    private String s3Bucket;

    public void uploadFile(String key, InputStream inputStream, long size) throws IOException {
        log.info("Uploading file to S3. Bucket: '{}', Key: '{}'", s3Bucket, key);
        try {
            s3Client.putObject(PutObjectRequest.builder()
                    .bucket(s3Bucket)
                    .key(key)
                    .build(),
                    RequestBody.fromInputStream(inputStream, size));
            log.info("Successfully uploaded file: '{}'", key);
        } catch (Exception e) {
            log.error("Failed to upload file to S3: '{}'", key, e);
            throw new IOException("Failed to upload file to S3", e);
        }
    }
}
