package com.lukk.ascend.ai.orchestrator.controller;

import com.lukk.ascend.ai.orchestrator.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.orchestrator.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.orchestrator.service.StorageService;
import io.swagger.v3.oas.annotations.Operation;
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

    @Operation(summary = "AscendAI upload endpoint", description = "Documents and images upload endpoint.")
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<String> uploadDocument(@RequestParam("file") MultipartFile file) {
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
