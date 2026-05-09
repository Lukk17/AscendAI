package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.VisionCapabilityProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Decides whether a (provider, model) pair supports image input. The map of
 * supported globs comes from {@link VisionCapabilityProperties}. When the
 * caller doesn't pass a model, the provider's default model is used. Matching
 * is case-insensitive so YAML globs like {@code *llava*} catch {@code LLAVA-13B}.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class VisionCapabilityResolver {

    private final VisionCapabilityProperties visionProperties;
    private final AiProviderProperties aiProviderProperties;

    public boolean supportsImages(String provider, String model) {
        String resolvedProvider = resolveProvider(provider);
        String resolvedModel = resolveModel(resolvedProvider, model);

        if (!StringUtils.hasText(resolvedModel)) {
            log.warn("[VisionCapabilityResolver] No model resolved for provider '{}' (caller passed model='{}'); denying image input",
                    resolvedProvider, model);
            return false;
        }

        List<String> patterns = visionProperties.getProviders().get(resolvedProvider);
        if (patterns == null || patterns.isEmpty()) {
            log.debug("[VisionCapabilityResolver] No vision globs configured for provider '{}'", resolvedProvider);
            return false;
        }

        String modelLower = resolvedModel.toLowerCase();
        for (String glob : patterns) {
            if (matchesGlob(glob.toLowerCase(), modelLower)) {
                return true;
            }
        }
        return false;
    }

    private String resolveProvider(String provider) {
        return Optional.ofNullable(provider)
                .filter(StringUtils::hasText)
                .map(String::trim)
                .map(String::toLowerCase)
                .orElse(aiProviderProperties.getDefaultProvider());
    }

    private String resolveModel(String provider, String model) {
        if (StringUtils.hasText(model)) {
            return model;
        }
        return Optional.ofNullable(aiProviderProperties.getProviders().get(provider))
                .map(AiProviderProperties.ProviderConfig::getModel)
                .orElse("");
    }

    private boolean matchesGlob(String glob, String model) {
        if (model == null || model.isEmpty()) {
            return false;
        }
        String regex = "^" + Pattern.quote(glob).replace("*", "\\E.*\\Q") + "$";
        return Pattern.matches(regex, model);
    }
}
