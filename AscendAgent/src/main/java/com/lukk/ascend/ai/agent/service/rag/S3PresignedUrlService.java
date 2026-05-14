package com.lukk.ascend.ai.agent.service.rag;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.dto.SourceFile;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadObjectResponse;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;

@Service
@Slf4j
public class S3PresignedUrlService {

    private static final Duration MIN_TTL = Duration.ofMinutes(1);
    private static final Duration MAX_TTL = Duration.ofHours(1);

    private final S3Presigner presigner;
    private final S3Client s3Client;
    private final RagProperties ragProperties;
    private final Executor taskExecutor;
    private final String publicEndpoint;
    private Duration effectiveTtl;

    public S3PresignedUrlService(S3Presigner presigner,
                                 S3Client s3Client,
                                 RagProperties ragProperties,
                                 Executor taskExecutor,
                                 @Value("${app.s3.public-endpoint:${app.s3.endpoint}}") String publicEndpoint) {
        this.presigner = presigner;
        this.s3Client = s3Client;
        this.ragProperties = ragProperties;
        this.taskExecutor = taskExecutor;
        this.publicEndpoint = publicEndpoint;
    }

    @PostConstruct
    void init() {
        Duration configured = ragProperties.getSourceAttachments().getPresignTtl();
        if (configured.compareTo(MIN_TTL) < 0) {
            log.warn("[S3PresignedUrlService] Configured presign TTL {} below minimum {}; clamping.", configured, MIN_TTL);
            effectiveTtl = MIN_TTL;
        } else if (configured.compareTo(MAX_TTL) > 0) {
            log.warn("[S3PresignedUrlService] Configured presign TTL {} above maximum {}; clamping.", configured, MAX_TTL);
            effectiveTtl = MAX_TTL;
        } else {
            effectiveTtl = configured;
        }
        log.info("[S3PresignedUrlService] Presigning against {} with TTL {}", publicEndpoint, effectiveTtl);
    }

    public List<SourceFile> presignAll(List<SourceRef> refs) {
        if (refs == null || refs.isEmpty()) {
            return List.of();
        }
        if (!ragProperties.getSourceAttachments().isEnabled()) {
            log.debug("[S3PresignedUrlService] Source attachments disabled; returning empty list");
            return List.of();
        }

        List<CompletableFuture<Optional<SourceFile>>> futures = new ArrayList<>(refs.size());
        for (SourceRef ref : refs) {
            futures.add(CompletableFuture.supplyAsync(() -> presign(ref), taskExecutor));
        }

        List<SourceFile> results = new ArrayList<>(refs.size());
        for (CompletableFuture<Optional<SourceFile>> f : futures) {
            try {
                f.join().ifPresent(results::add);
            } catch (Exception e) {
                log.warn("[S3PresignedUrlService] Presign task failed: {}", e.getMessage());
            }
        }
        return results;
    }

    private Optional<SourceFile> presign(SourceRef ref) {
        long maxBytes = ragProperties.getSourceAttachments().getMaxFileSize().toBytes();

        Long sizeBytes = null;
        String mimeType = ref.mimeType();
        try {
            HeadObjectResponse head = s3Client.headObject(HeadObjectRequest.builder()
                    .bucket(ref.bucket())
                    .key(ref.key())
                    .build());
            sizeBytes = head.contentLength();
            if (sizeBytes != null && sizeBytes > maxBytes) {
                log.warn("[S3PresignedUrlService] Skipping source attachment for {} ({} > {} bytes)",
                        ref.s3Uri(), sizeBytes, maxBytes);
                return Optional.empty();
            }
            if (mimeType == null && head.contentType() != null) {
                mimeType = head.contentType();
            }
        } catch (Exception e) {
            log.warn("[S3PresignedUrlService] HEAD failed for {}: {}", ref.s3Uri(), e.getMessage());
            return Optional.empty();
        }

        try {
            GetObjectPresignRequest presignRequest = GetObjectPresignRequest.builder()
                    .signatureDuration(effectiveTtl)
                    .getObjectRequest(b -> b.bucket(ref.bucket()).key(ref.key()))
                    .build();
            PresignedGetObjectRequest presigned = presigner.presignGetObject(presignRequest);
            Instant expiresAt = Instant.now().plus(effectiveTtl);

            log.info("[S3PresignedUrlService] Presigned {} (TTL {})", ref.s3Uri(), effectiveTtl);
            return Optional.of(new SourceFile(
                    ref.displayName(),
                    mimeType,
                    presigned.url().toString(),
                    expiresAt,
                    sizeBytes));
        } catch (Exception e) {
            log.warn("[S3PresignedUrlService] Presign failed for {}: {}", ref.s3Uri(), e.getMessage());
            return Optional.empty();
        }
    }
}
