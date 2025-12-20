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

/**
 * Service responsible for handling storage operations, particularly with S3.
 * <p>
 * This service abstracts S3 interactions, allowing the rest of the application
 * to
 * be agnostic of the underlying storage implementation details.
 * </p>
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class StorageService {

    private final S3Client s3Client;

    @Value("${app.s3.bucket:knowledge-base}")
    private String s3Bucket;

    /**
     * Uploads a file to the configured S3 bucket.
     *
     * @param key         The key (path) under which the file should be stored.
     * @param inputStream The content of the file.
     * @param size        The size of the content.
     * @throws IOException If the upload fails due to I/O errors.
     */
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
