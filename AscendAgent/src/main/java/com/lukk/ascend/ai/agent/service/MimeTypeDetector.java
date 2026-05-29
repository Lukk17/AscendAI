package com.lukk.ascend.ai.agent.service;

import lombok.extern.slf4j.Slf4j;
import org.apache.tika.Tika;
import org.apache.tika.metadata.Metadata;
import org.apache.tika.metadata.TikaCoreProperties;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;

/**
 * Detects an upload's true MIME type by reading the first bytes of the file
 * with Apache Tika. The client-supplied {@code Content-Type} is never trusted
 * — an attacker can label a payload as anything, so the allowlist check has to
 * sniff the bytes server-side.
 *
 * <p>Falls back to the client-supplied header (or {@code application/octet-stream})
 * only if Tika fails entirely, which keeps the upload path resilient if a
 * file is too short to detect.
 */
@Slf4j
@Service
public class MimeTypeDetector {

    private final Tika tika = new Tika();

    public String detect(MultipartFile file, String sanitizedFilename) {
        try (InputStream stream = file.getInputStream()) {
            Metadata metadata = new Metadata();
            if (sanitizedFilename != null) {
                metadata.set(TikaCoreProperties.RESOURCE_NAME_KEY, sanitizedFilename);
            }
            String detected = tika.detect(stream, metadata);
            return detected != null ? detected.toLowerCase() : fallback(file);
        } catch (IOException e) {
            log.warn("[MimeTypeDetector] Tika sniff failed for '{}'; falling back to client header. Reason: {}",
                    sanitizedFilename, e.getMessage());
            return fallback(file);
        }
    }

    private String fallback(MultipartFile file) {
        String declared = file.getContentType();
        return declared != null ? declared.toLowerCase() : "application/octet-stream";
    }
}
