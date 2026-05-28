package com.lukk.ascend.ai.agent.dto;

import java.util.List;

/**
 * Response body for {@code POST /api/v1/ingestion/upload}. Contains the keys
 * successfully uploaded to MinIO and a parallel list of failures (one entry
 * per file that was rejected, including the disallowed-MIME and IO failures).
 *
 * @param uploaded keys that landed in S3 in upload order
 * @param failures human-readable per-file error strings; empty on full success
 */
public record UploadResponse(List<String> uploaded, List<String> failures) {
}
