package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.agent.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.agent.service.ManualIngestionService;
import com.lukk.ascend.ai.agent.service.StorageService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Optional;

/**
 * Controller for handling file ingestion requests.
 * <p>
 * This controller exposes endpoints for uploading documents to be processed
 * by the ingestion pipeline.
 * </p>
 */
@Slf4j
@RestController
@RequiredArgsConstructor
@Tag(name = "Ingestion", description = "External documents ingestion controller.")
@RequestMapping(value = "/api/ingestion", produces = "application/json")
public class IngestionController {

    @Value("${app.ingestion.folders.obsidian:obsidian/}")
    private String obsidianFolder;

    @Value("${app.ingestion.folders.documents:documents/}")
    private String documentsFolder;

    private final StorageService storageService;
    private final ManualIngestionService manualIngestionService;

    @Operation(summary = "AscendAI upload endpoint", description = "Documents and images upload endpoint.")
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<String> uploadDocument(
            @Parameter(description = "File to upload. Markdown files (.md) go to obsidian/ folder, others to documents/ folder.", required = true)
            @RequestParam("file") MultipartFile file) {
        if (file.isEmpty()) {
            return ResponseEntity.badRequest().body("File is empty");
        }

        try {
            String folder = determineFolder(file.getOriginalFilename());
            String key = folder + (file.getOriginalFilename() != null ? file.getOriginalFilename() : "unknown_file");

            storageService.uploadFile(key, file.getInputStream(), file.getSize());

            return ResponseEntity.ok("File uploaded to: " + key);
        } catch (IOException e) {
            log.error("Error uploading file", e);
            return ResponseEntity.internalServerError().body("Failed to upload file: " + e.getMessage());
        }
    }

    @Operation(summary = "Run ingestion", description = "Manually scans the S3 bucket and ingests new/updated files into the vector store for the specified embedding provider.")
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/run")
    public ResponseEntity<ManualIngestionService.ManualIngestionResult> runIngestion(
            @Parameter(description = "Optional S3 key prefix to limit scan scope. If omitted, scans the entire bucket.", example = "obsidian/")
            @RequestParam(value = "prefix", required = false) String prefix,

            @Parameter(description = "Embedding provider to use for ingestion. Determines which collection (768 or 1536) documents are embedded into. "
                    + "Available: lmstudio (768-dim), gemini (768-dim), openai (1536-dim). Defaults to EMBEDDING_PROVIDER env var.",
                    example = "lmstudio")
            @RequestParam(value = "embeddingProvider", required = false) String embeddingProvider) {
        return ResponseEntity.ok(manualIngestionService.run(Optional.ofNullable(prefix), embeddingProvider));
    }

    /**
     * Determines the folder path based on the filename.
     *
     * @param filename The name of the file.
     * @return The folder path (including trailing slash).
     */
    private String determineFolder(String filename) {
        if (filename != null && filename.endsWith(".md")) {
            return obsidianFolder + "/";
        } else {
            return documentsFolder + "/";
        }
    }
}
