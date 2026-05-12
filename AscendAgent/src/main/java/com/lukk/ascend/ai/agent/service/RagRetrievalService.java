package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class RagRetrievalService {

    private final VectorStoreResolver vectorStoreResolver;
    private final RagProperties ragProperties;

    public String retrieveContext(String query, String embeddingProvider) {
        if (!ragProperties.isEnabled()) {
            return "";
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
            return "";
        }

        log.info("[RagRetrievalService] Retrieval: {}/{} candidates above threshold={} - scores={}, inject=YES",
                kept.size(), candidates.size(), threshold, scoreList);

        return buildContextBlock(kept);
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
            List<Document> documents = vectorStore.similaritySearch(searchRequest);
            return documents != null ? documents : List.of();
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
