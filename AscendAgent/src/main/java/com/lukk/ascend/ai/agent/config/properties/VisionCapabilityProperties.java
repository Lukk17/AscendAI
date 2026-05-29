package com.lukk.ascend.ai.agent.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Per-provider list of model name patterns that support image input. The matcher
 * is glob-style — {@code *} stands for any character sequence — so entries like
 * {@code claude-*}, {@code gpt-4o*}, {@code *-vl-*} all work without writing
 * regex literals in the YAML.
 */
@Getter
@Setter
@ConfigurationProperties(prefix = "app.ai.vision")
public class VisionCapabilityProperties {

    private Map<String, List<String>> providers = new LinkedHashMap<>();
}
