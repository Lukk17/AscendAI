package com.lukk.ascend.ai.agent.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.Filter;
import org.springframework.ai.vectorstore.filter.FilterExpressionBuilder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@Slf4j
public class DocumentService {

    @Value("${app.ingestion.token-splitter.chunk-size:1000}")
    private int tokenSplitterChunkSize;

    @Value("${app.ingestion.token-splitter.min-chunk-size-chars:350}")
    private int minChunkSizeChars;

    @Value("${app.ingestion.token-splitter.min-chunk-length-to-embed:5}")
    private int minChunkLengthToEmbed;

    @Value("${app.ingestion.token-splitter.max-num-chunks:10000}")
    private int maxNumChunks;

    @Value("${app.ingestion.token-splitter.keep-separator:true}")
    private boolean keepSeparator;

    public void removeOldDocuments(List<Document> documents, VectorStore vectorStore) {
        if (documents == null || documents.isEmpty()) {
            return;
        }

        Object sourceObj = documents.get(0).getMetadata().get("source");
        if (sourceObj instanceof String filename) {
            log.info("Removing old documents for source: {}", filename);
            Filter.Expression filterExpression = new FilterExpressionBuilder()
                    .eq("source", filename)
                    .build();
            vectorStore.delete(filterExpression);
        }
    }

    public List<Document> splitDocuments(List<Document> documents) {
        log.info("Splitting {} documents into chunks using chunk size: {}", documents.size(),
                tokenSplitterChunkSize);
        TokenTextSplitter splitter = new TokenTextSplitter(
                tokenSplitterChunkSize,
                minChunkSizeChars,
                minChunkLengthToEmbed,
                maxNumChunks,
                keepSeparator,
                List.of('.', '!', '?', ';', '\n'));
        List<Document> splitDocs = splitter.apply(documents);
        log.info("Split into {} chunks.", splitDocs.size());
        return splitDocs;
    }
}
