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

        SearchRequest searchRequest = SearchRequest.builder()
                .query(query)
                .topK(ragProperties.getTopK())
                .similarityThreshold(SearchRequest.SIMILARITY_THRESHOLD_ACCEPT_ALL)
                .build();

        List<Document> documents = performSimilaritySearch(vectorStore, searchRequest);
        if (documents.isEmpty()) {
            return "";
        }

        Double topScore = documents.get(0).getScore();
        double score = topScore != null ? topScore : 0.0d;
        boolean isAboveThreshold = score >= ragProperties.getSimilarityThreshold();

        log.info("[RagRetrievalService] Retrieval: docs={}, topScore={}, threshold={}, inject={}",
                documents.size(), topScore, ragProperties.getSimilarityThreshold(), isAboveThreshold);

        if (!isAboveThreshold) {
            return "";
        }

        return buildContextBlock(documents);
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
