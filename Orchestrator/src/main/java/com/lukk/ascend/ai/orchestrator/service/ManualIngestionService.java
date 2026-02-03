package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.exception.IngestionException;
import com.lukk.ascend.ai.orchestrator.service.ingestion.IngestionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.stereotype.Service;
import software.amazon.awssdk.core.ResponseInputStream;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Request;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Response;
import software.amazon.awssdk.services.s3.model.S3Object;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class ManualIngestionService {

    private final S3Client s3Client;
    private final ConcurrentMetadataStore metadataStore;
    private final IngestionService ingestionService;
    private final DocumentService documentService;
    private final VectorStore vectorStore;

    @Value("${app.s3.bucket}")
    private String bucket;

    @Value("${app.ingestion.folders.obsidian:obsidian/}")
    private String obsidianFolder;

    @Value("${app.ingestion.folders.documents:documents/}")
    private String documentsFolder;

    public ManualIngestionResult run(Optional<String> prefix) {
        String continuationToken = null;
        ManualIngestionResult result = new ManualIngestionResult();

        do {
            ListObjectsV2Response response = listObjects(prefix, continuationToken);
            continuationToken = response.nextContinuationToken();

            for (S3Object object : response.contents()) {
                processObject(object, result);
            }
        } while (continuationToken != null && !continuationToken.isBlank());

        return result;
    }

    private ListObjectsV2Response listObjects(Optional<String> prefix, String continuationToken) {
        ListObjectsV2Request.Builder builder = ListObjectsV2Request.builder()
                .bucket(bucket)
                .maxKeys(1000);

        prefix.filter(p -> !p.isBlank()).ifPresent(builder::prefix);

        if (continuationToken != null && !continuationToken.isBlank()) {
            builder.continuationToken(continuationToken);
        }

        return s3Client.listObjectsV2(builder.build());
    }

    private void processObject(S3Object object, ManualIngestionResult result) {
        String key = object.key();
        if (key == null || key.isBlank()) {
            return;
        }

        if (!shouldIngestKey(key)) {
            result.skipped++;
            return;
        }

        String version = buildVersion(object);
        String metadataKey = buildMetadataKey(key, version);
        String existing = metadataStore.putIfAbsent(metadataKey, Instant.now().toString());
        if (existing != null) {
            result.skipped++;
            return;
        }

        try {
            ingestObject(key, result);
        } catch (Exception e) {
            result.failed++;
            log.error("Manual ingestion failed for key: {}", key, e);
        }
    }

    private void ingestObject(String key, ManualIngestionResult result) {
        try (ResponseInputStream<GetObjectResponse> stream = s3Client.getObject(GetObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .build())) {

            List<Document> documents = key.toLowerCase().endsWith(".md") || key.toLowerCase().contains(obsidianFolder)
                    ? ingestionService.processMarkdown(stream, key)
                    : ingestionService.processUnstructured(stream, key);

            if (documents == null || documents.isEmpty()) {
                result.skipped++;
                return;
            }

            documentService.removeOldDocuments(documents, vectorStore);

            List<Document> chunks = documentService.splitDocuments(documents);
            for (Document chunk : chunks) {
                vectorStore.add(List.of(chunk));
                result.indexed++;
            }
        } catch (Exception e) {
            throw new IngestionException("Manual ingestion failed for key: " + key, e);
        }
    }

    private boolean shouldIngestKey(String key) {
        String path = key.toLowerCase();
        if (path.endsWith(".md") || path.contains(obsidianFolder)) {
            return true;
        }
        return path.contains(documentsFolder);
    }

    private String buildVersion(S3Object object) {
        String etag = object.eTag();
        if (etag != null && !etag.isBlank()) {
            return etag;
        }
        Instant lastModified = object.lastModified();
        return lastModified != null ? lastModified.toString() : "unknown";
    }

    private String buildMetadataKey(String key, String version) {
        return "manual-ingestion:" + key + ":" + version;
    }

    public static class ManualIngestionResult {
        public int indexed;
        public int skipped;
        public int failed;
    }
}
