package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.ingestion.DocumentRouter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentIngestionService {

    private final DocumentRouter documentRouter;

    public String processDocument(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return "";
        }

        String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "document";
        log.info("[DocumentIngestionService] Processing document for prompt context: {}", filename);

        byte[] fileBytes = readFileBytes(file, filename);
        List<Document> documents = documentRouter.routeAndProcess(fileBytes, filename, file.getContentType());

        String content = documents.stream()
                .map(Document::getText)
                .reduce("", (a, b) -> a + "\n" + b);

        return "\n\n<document_context>\n" + content + "\n</document_context>\n";
    }

    private byte[] readFileBytes(MultipartFile file, String filename) {
        try {
            return file.getBytes();
        } catch (IOException e) {
            throw new IngestionException("Failed to read file bytes: " + filename, e);
        }
    }
}
