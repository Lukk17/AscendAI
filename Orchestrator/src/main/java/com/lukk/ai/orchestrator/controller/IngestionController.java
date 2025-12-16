package com.lukk.ai.orchestrator.controller;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.io.IOException;

@RestController
@RequestMapping("/api/ingestion")
public class IngestionController {

    private final S3Client s3Client;
    private final String s3Bucket = "knowledge-base";

    public IngestionController(S3Client s3Client) {
        this.s3Client = s3Client;
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<String> uploadDocument(@RequestParam("file") MultipartFile file) {
        if (file.isEmpty()) {
            return ResponseEntity.badRequest().body("File is empty");
        }

        try {
            // Determine folder based on file type (basic logic)
            String key = file.getOriginalFilename();
            // Optional: Route to specific folders if needed (obsidian/documents)
            // For now, let's put .md in obsidian, others in documents
            if (key != null && key.endsWith(".md")) {
                key = "obsidian/" + key;
            } else {
                key = "documents/" + key;
            }

            s3Client.putObject(PutObjectRequest.builder()
                            .bucket(s3Bucket)
                            .key(key)
                            .build(),
                    RequestBody.fromInputStream(file.getInputStream(), file.getSize()));

            return ResponseEntity.ok("File uploaded to S3: " + key);
        } catch (IOException e) {
            return ResponseEntity.internalServerError().body("Failed to upload file: " + e.getMessage());
        }
    }
}
