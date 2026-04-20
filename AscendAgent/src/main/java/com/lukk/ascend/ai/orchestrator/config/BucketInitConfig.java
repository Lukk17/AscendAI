package com.lukk.ascend.ai.orchestrator.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.NoSuchBucketException;

@Configuration
@Slf4j
public class BucketInitConfig {

    @Value("${app.s3.bucket}")
    private String s3Bucket;

    @Bean
    public CommandLineRunner initBucket(S3Client s3Client) {
        return args -> {
            try {
                s3Client.headBucket(b -> b.bucket(s3Bucket));
                log.info("Bucket '{}' already exists.", s3Bucket);
            } catch (NoSuchBucketException e) {
                log.info("Bucket '{}' not found. Creating...", s3Bucket);
                s3Client.createBucket(b -> b.bucket(s3Bucket));
                log.info("Bucket '{}' created successfully.", s3Bucket);
            } catch (Exception e) {
                log.error("Failed to check/create bucket '{}'", s3Bucket, e);
            }
        };
    }
}

