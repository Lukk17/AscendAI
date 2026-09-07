package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

/**
 * Bound from {@code app.ingestion.upload.*} in application.yaml.
 *
 * <p>Uses {@code @ConfigurationProperties} rather than {@code @Value} with a colon-default
 * because Spring's {@code @Value} does not bind YAML lists — it silently returned an empty
 * list at runtime, disabling the MIME allowlist check.
 */
@Getter
@Setter
@ConfigurationProperties(prefix = "app.ingestion.upload")
public class IngestionUploadProperties {

    private List<String> allowedMimeTypes = new ArrayList<>();
}
