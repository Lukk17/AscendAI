package com.lukk.ascend.ai.agent.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import io.swagger.v3.oas.annotations.media.Schema;

import java.time.Instant;

@JsonInclude(JsonInclude.Include.NON_NULL)
@Schema(description = "A source document that grounded the RAG-backed answer.")
public record SourceFile(
        @Schema(description = "Human-readable filename") String name,
        @Schema(description = "MIME type, e.g. application/pdf") String mimeType,
        @Schema(description = "Presigned GET URL for the source object") String downloadUrl,
        @Schema(description = "URL expiry as ISO-8601 instant") Instant expiresAt,
        @Schema(description = "Object size in bytes; omitted when unknown") Long sizeBytes
) {
}
