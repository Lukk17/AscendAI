package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.VectorStoreProperties;
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
import software.amazon.awssdk.services.s3.model.*;

import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class ManualIngestionService {

    private final S3Client s3Client;
    private final ConcurrentMetadataStore metadataStore;
    private final IngestionService ingestionService;
    private final DocumentService documentService;
    private final VectorStoreResolver vectorStoreResolver;
    private final VectorStoreProperties vectorStoreProperties;

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

        ingestObject(key, result);
    }

    private void ingestObject(String key, ManualIngestionResult result) {
        try (ResponseInputStream<GetObjectResponse> stream = s3Client.getObject(GetObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .build())) {

            boolean isMarkdown = key.toLowerCase().endsWith(".md") || key.toLowerCase().contains(obsidianFolder);
            List<Document> documents = isMarkdown
                    ? ingestionService.processMarkdown(stream, key)
                    : ingestionService.processUnstructured(stream, key);

            if (documents == null || documents.isEmpty()) {
                result.skipped++;
                return;
            }

            List<Document> chunks = documentService.splitDocuments(documents);
            ingestIntoAllCollections(chunks, key);
            result.indexed += chunks.size();
        } catch (IngestionException e) {
            result.failed++;
            log.error("[ManualIngestionService] Ingestion failed for key: {}", key, e);
        } catch (IOException e) {
            result.failed++;
            throw new IngestionException("Failed to read S3 object: " + key, e);
        }
    }

    private void ingestIntoAllCollections(List<Document> chunks, String key) {
        vectorStoreProperties.getCollections().forEach(config -> {
            VectorStore store = vectorStoreResolver.resolve(resolveProviderForCollection(config.getName()));
            log.info("[ManualIngestionService] Ingesting {} chunks into collection '{}' for key: {}",
                    chunks.size(), config.getName(), key);
            documentService.removeOldDocuments(chunks, store);
            for (Document chunk : chunks) {
                store.add(List.of(chunk));
            }
        });
    }

    private String resolveProviderForCollection(String collectionName) {
        return vectorStoreProperties.getProviderCollectionMapping().entrySet().stream()
                .filter(entry -> entry.getValue().equals(collectionName))
                .map(Map.Entry::getKey)
                .findFirst()
                .orElse(null);
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
