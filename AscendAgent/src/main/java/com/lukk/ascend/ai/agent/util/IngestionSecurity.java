package com.lukk.ascend.ai.agent.util;

import org.springframework.util.StringUtils;

/**
 * Filename sanitization helpers for ingestion uploads.
 *
 * <p>S3 keys are derived from {@code MultipartFile#getOriginalFilename()}, which the client
 * controls. Without sanitization an attacker can pass {@code ../../etc/passwd} or non-printable
 * characters and end up with a key that maps to an unexpected location or breaks downstream
 * tooling. This utility normalizes filenames into a safe character set so they can be used as
 * S3 keys, Qdrant {@code source} metadata, or filesystem paths.
 */
public final class IngestionSecurity {

    private static final int MAX_LENGTH = 200;
    private static final String FALLBACK_NAME = "unknown_file";

    private IngestionSecurity() {
    }

    /**
     * Returns a filesystem- and S3-safe filename. The pipeline is:
     * <ol>
     *   <li>Strip path separators via {@link StringUtils#cleanPath(String)} so {@code ../../} segments
     *       are resolved away before sanitization.</li>
     *   <li>Drop any path component that survived (anything before the last {@code /}).</li>
     *   <li>Strip ASCII control characters.</li>
     *   <li>Collapse runs of {@code .} (more than one) into a single dot — neutralizes
     *       {@code ..filename} and similar disguised traversal sequences.</li>
     *   <li>Replace anything outside {@code [A-Za-z0-9._-]} with {@code _}.</li>
     *   <li>Collapse repeated underscores.</li>
     *   <li>Strip leading dots and underscores in a single pass (no hidden files, no leading garbage).</li>
     *   <li>Cap length at 200 chars, preserving the extension when it fits.</li>
     * </ol>
     * Returns {@link #FALLBACK_NAME} when the input is null, blank, or sanitizes down to nothing.
     */
    public static String sanitizeFilename(String original) {
        if (original == null) {
            return FALLBACK_NAME;
        }
        String cleaned = StringUtils.cleanPath(original);
        int lastSep = cleaned.lastIndexOf('/');
        String tail = lastSep >= 0 ? cleaned.substring(lastSep + 1) : cleaned;

        String stripped = tail.replaceAll("\\p{Cntrl}", "");
        String dotsCollapsed = stripped.replaceAll("\\.{2,}", ".");
        String safe = dotsCollapsed.replaceAll("[^A-Za-z0-9._-]", "_");
        safe = safe.replaceAll("_+", "_");

        while (!safe.isEmpty() && (safe.charAt(0) == '.' || safe.charAt(0) == '_')) {
            safe = safe.substring(1);
        }

        if (safe.isBlank()) {
            return FALLBACK_NAME;
        }
        if (safe.length() > MAX_LENGTH) {
            safe = truncatePreservingExtension(safe);
        }
        return safe;
    }

    private static String truncatePreservingExtension(String name) {
        int dotIdx = name.lastIndexOf('.');
        if (dotIdx <= 0 || dotIdx >= name.length() - 1) {
            return name.substring(0, MAX_LENGTH);
        }
        String ext = name.substring(dotIdx);
        if (ext.length() >= MAX_LENGTH) {
            return name.substring(0, MAX_LENGTH);
        }
        int baseLen = MAX_LENGTH - ext.length();
        return name.substring(0, baseLen) + ext;
    }
}
