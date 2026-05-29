package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

/**
 * Bound from {@code app.ingestion.upload.*} in application.yaml.
 *
 * <p>Migrated from {@code @Value("${app.ingestion.upload.allowed-mime-types:}")} on the
 * controller because Spring's {@code @Value} with a colon-default does not bind YAML lists —
 * it returned an empty list at runtime, silently disabling the MIME allowlist enforcement.
 */
@Getter
@Setter
@ConfigurationProperties(prefix = "app.ingestion.upload")
public class IngestionUploadProperties {

    /**
     * MIME types that the ingestion upload endpoint will accept after Tika sniffing.
     * An empty list disables enforcement (controller short-circuits the check).
     */
    private List<String> allowedMimeTypes = new ArrayList<>();
}
