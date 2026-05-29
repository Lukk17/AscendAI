package com.lukk.ascend.ai.agent.service.rag;
import com.lukk.ascend.ai.agent.service.provider.VectorStoreResolver;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionMetadataKeys;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalResult;
import com.lukk.ascend.ai.agent.service.rag.SourceRef;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
@Slf4j
public class RagRetrievalService {

    private static final String META_BUCKET = "bucket";
    private static final String META_KEY = "key";
    private static final String META_DISPLAY_NAME = "displayName";
    private static final String META_MIME_TYPE = "mimeType";

    private final VectorStoreResolver vectorStoreResolver;
    private final RagProperties ragProperties;
    private final String defaultBucket;

    public RagRetrievalService(VectorStoreResolver vectorStoreResolver,
                               RagProperties ragProperties,
                               @Value("${app.s3.bucket}") String defaultBucket) {
        this.vectorStoreResolver = vectorStoreResolver;
        this.ragProperties = ragProperties;
        this.defaultBucket = defaultBucket;
    }

    public RagRetrievalResult retrieve(String query, String embeddingProvider) {
        if (!ragProperties.isEnabled()) {
            return RagRetrievalResult.skipped();
        }

        VectorStore vectorStore = vectorStoreResolver.resolve(embeddingProvider);
        String collectionName = vectorStoreResolver.resolveProviderName(embeddingProvider);
        log.info("Executing RAG retrieval against Qdrant collection: '{}' (embeddingProvider={}, topK={})",
                collectionName, embeddingProvider, ragProperties.getTopK());

        // Fetch all top-K candidates without a Qdrant-side threshold so we can log
        // the actual raw scores (including near-misses) and threshold-filter in Java.
        // Lets operators see why retrieval missed at the current floor and tune it
        // empirically instead of guessing.
        SearchRequest searchRequest = SearchRequest.builder()
                .query(query)
                .topK(ragProperties.getTopK())
                .similarityThreshold(0.0d)
                .build();

        List<Document> candidates = performSimilaritySearch(vectorStore, searchRequest);
        double threshold = ragProperties.getSimilarityThreshold();
        String scoreList = formatScores(candidates);

        List<Document> kept = candidates.stream()
                .filter(d -> d.getScore() != null && d.getScore() >= threshold)
                .toList();

        if (kept.isEmpty()) {
            log.info("[RagRetrievalService] Retrieval: 0/{} candidates above threshold={} - scores={}",
                    candidates.size(), threshold, scoreList);
            return RagRetrievalResult.empty();
        }

        log.info("[RagRetrievalService] Retrieval: {}/{} candidates above threshold={} - scores={}, inject=YES",
                kept.size(), candidates.size(), threshold, scoreList);

        return new RagRetrievalResult(buildContextBlock(kept), buildSourceRefs(kept), true);
    }

    private List<SourceRef> buildSourceRefs(List<Document> documents) {
        Map<String, SourceRef> dedup = new LinkedHashMap<>();
        for (Document doc : documents) {
            Map<String, Object> meta = doc.getMetadata();
            String key = stringMeta(meta, META_KEY);
            if (key == null) {
                key = stringMeta(meta, IngestionMetadataKeys.SOURCE);
            }
            if (key == null || key.isBlank()) {
                log.debug("[RagRetrievalService] Skipping source-tracking for chunk with no key/source metadata");
                continue;
            }

            String bucket = stringMeta(meta, META_BUCKET);
            if (bucket == null || bucket.isBlank()) {
                bucket = defaultBucket;
            }

            String displayName = stringMeta(meta, META_DISPLAY_NAME);
            if (displayName == null) {
                displayName = stringMeta(meta, IngestionMetadataKeys.TITLE);
            }
            if (displayName == null) {
                displayName = basename(key);
            }

            String mimeType = stringMeta(meta, META_MIME_TYPE);

            String dedupKey = bucket + "::" + key;
            dedup.putIfAbsent(dedupKey, new SourceRef(bucket, key, displayName, mimeType));
        }
        return List.copyOf(dedup.values());
    }

    private static String stringMeta(Map<String, Object> meta, String key) {
        Object v = meta == null ? null : meta.get(key);
        return v == null ? null : v.toString();
    }

    private static String basename(String key) {
        int slash = key.lastIndexOf('/');
        return slash >= 0 ? key.substring(slash + 1) : key;
    }

    private String formatScores(List<Document> documents) {
        if (documents.isEmpty()) {
            return "[]";
        }
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < documents.size(); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            Double score = documents.get(i).getScore();
            sb.append(score != null ? String.format("%.3f", score) : "null");
        }
        sb.append("]");
        return sb.toString();
    }

    private List<Document> performSimilaritySearch(VectorStore vectorStore, SearchRequest searchRequest) {
        try {
            return vectorStore.similaritySearch(searchRequest);

        } catch (Exception e) {
            log.warn("[RagRetrievalService] Similarity search failed (embedding service may be unavailable): {}",
                    e.getMessage());

            return List.of();
        }
    }

    private String buildContextBlock(List<Document> documents) {
        int remaining = ragProperties.getMaxContextChars();
        StringBuilder context = new StringBuilder();
        context.append("<rag_context>\n");
        context.append("The following context may be relevant. Use it only if it helps; otherwise ignore it.\n\n");

        for (Document doc : documents) {
            if (remaining <= 0) {
                break;
            }

            String text = doc.getText();
            if (text == null || text.isBlank()) {
                continue;
            }

            String snippet = text.length() > remaining ? text.substring(0, remaining) : text;
            context.append(snippet).append("\n\n");
            remaining -= snippet.length();
        }

        context.append("</rag_context>");
        return context.toString();
    }
}
