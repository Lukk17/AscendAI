package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.agent.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.agent.config.properties.IngestionUploadProperties;
import com.lukk.ascend.ai.agent.dto.ApiError;
import com.lukk.ascend.ai.agent.dto.UploadResponse;
import com.lukk.ascend.ai.agent.service.ingestion.ManualIngestionService;
import com.lukk.ascend.ai.agent.service.ingestion.MimeTypeDetector;
import com.lukk.ascend.ai.agent.service.storage.StorageService;
import com.lukk.ascend.ai.agent.util.IngestionSecurity;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

@Slf4j
@RestController
@RequiredArgsConstructor
@Tag(name = "Ingestion", description = "External documents ingestion controller.")
@RequestMapping(value = "/api/v1/ingestion", produces = "application/json")
public class IngestionController {

    @Value("${app.ingestion.folders.markdown:markdown/}")
    private String markdownFolder;

    @Value("${app.ingestion.folders.documents:documents/}")
    private String documentsFolder;

    private final StorageService storageService;
    private final ManualIngestionService manualIngestionService;
    private final MimeTypeDetector mimeTypeDetector;
    private final IngestionUploadProperties uploadProperties;

    @Operation(summary = "AscendAI upload endpoint",
            description = "Upload one or more files in a single request. Send multiple multipart parts with the same field name 'file'. "
                    + "Markdown files (.md) go to markdown/ folder, others to documents/ folder.")
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<?> uploadDocument(
            @Parameter(description = "One or more files to upload. Repeat the 'file' part to send multiple. "
                    + "Markdown files (.md) go to markdown/ folder, others to documents/ folder.", required = true)
            @RequestParam("file") List<MultipartFile> files) {
        if (files == null || files.isEmpty() || files.stream().allMatch(MultipartFile::isEmpty)) {
            return ResponseEntity.badRequest()
                    .body(new ApiError(HttpStatus.BAD_REQUEST.value(), "no_file", "No file provided"));
        }

        List<String> uploadedKeys = new ArrayList<>();
        List<String> failures = new ArrayList<>();

        List<String> configured = uploadProperties.getAllowedMimeTypes();
        Set<String> allowed = configured != null ? new HashSet<>(configured) : Set.of();
        for (MultipartFile file : files) {
            if (file.isEmpty()) {
                continue;
            }

            String safeName = IngestionSecurity.sanitizeFilename(file.getOriginalFilename());
            String detected = mimeTypeDetector.detect(file, safeName).toLowerCase();
            if (!allowed.isEmpty() && !allowed.contains(detected)) {
                log.warn("Rejecting upload '{}' with disallowed sniffed type '{}' (client said '{}')",
                        safeName, detected, file.getContentType());
                failures.add(safeName + ": disallowed type '" + detected + "'");
                continue;
            }

            String folder = determineFolder(safeName);
            String key = folder + safeName;

            try {
                storageService.uploadFile(key, file.getInputStream(), file.getSize());
                uploadedKeys.add(key);
            } catch (IOException e) {
                log.error("Error uploading file: {}", key, e);
                failures.add(key + ": " + e.getMessage());
            }
        }

        if (uploadedKeys.isEmpty()) {
            return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE)
                    .body(new ApiError(HttpStatus.UNSUPPORTED_MEDIA_TYPE.value(),
                            "unsupported_media_type",
                            "No files uploaded: " + String.join("; ", failures)));
        }

        return ResponseEntity.ok(new UploadResponse(uploadedKeys, failures));
    }

    @Operation(summary = "Run ingestion", description = "Manually scans the S3 bucket and ingests new/updated files into the vector store for the specified embedding provider.")
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/run")
    public ResponseEntity<ManualIngestionService.ManualIngestionResult> runIngestion(
            @Parameter(description = "Optional S3 key prefix to limit scan scope. If omitted, scans the entire bucket.", example = "markdown/")
            @RequestParam(value = "prefix", required = false) String prefix,

            @Parameter(description = "Embedding provider to use for ingestion. Determines which collection (768 or 1536) documents are embedded into. "
                    + "Available: lmstudio (768-dim), gemini (768-dim), openai (1536-dim). Defaults to EMBEDDING_PROVIDER env var.",
                    example = "lmstudio")
            @RequestParam(value = "embeddingProvider", required = false) String embeddingProvider) {
        return ResponseEntity.ok(manualIngestionService.run(Optional.ofNullable(prefix), embeddingProvider));
    }

    private String determineFolder(String filename) {
        if (filename != null && filename.endsWith(".md")) {
            return markdownFolder + "/";
        } else {
            return documentsFolder + "/";
        }
    }
}
