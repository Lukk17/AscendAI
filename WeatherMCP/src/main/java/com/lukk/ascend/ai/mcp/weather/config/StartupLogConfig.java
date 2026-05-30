package com.lukk.ascend.ai.mcp.weather.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.context.event.EventListener;
import org.springframework.core.env.Environment;
import org.springframework.core.io.Resource;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

@Component
@Slf4j
public class StartupLogConfig {

    private static final String DIVIDER = "----------------------------------------------------------";

    private static final Duration PROBE_TIMEOUT = Duration.ofSeconds(2);
    private static final Pattern BANNER_PLACEHOLDER = Pattern.compile("\\$\\{[^}]+}");

    private final Environment env;
    private final ObjectProvider<ToolCallbackProvider> toolCallbackProvider;
    private final String banner;

    public StartupLogConfig(Environment env,
                            ObjectProvider<ToolCallbackProvider> toolCallbackProvider,
                            @Value("classpath:/banner.txt") Resource bannerResource) {
        this.env = env;
        this.toolCallbackProvider = toolCallbackProvider;
        this.banner = loadBanner(bannerResource);
    }

    private String loadBanner(Resource bannerResource) {
        try (var in = bannerResource.getInputStream()) {
            String raw = new String(in.readAllBytes(), StandardCharsets.UTF_8);

            return BANNER_PLACEHOLDER.matcher(raw).replaceAll("").stripTrailing();
        } catch (IOException e) {
            log.debug("Could not load banner.txt; falling back to empty banner", e);

            return "";
        }
    }

    @EventListener
    public void onReadinessChange(AvailabilityChangeEvent<ReadinessState> event) {
        if (event.getState() != ReadinessState.ACCEPTING_TRAFFIC) {
            return;
        }
        String port = env.getProperty("local.server.port", env.getProperty("server.port", "9998"));
        String protocol = env.getProperty("server.ssl.key-store") != null ? "https" : "http";
        String hostAddress = resolveHostAddress();
        String appName = env.getProperty("spring.application.name", "ascend-ai-weather-mcp");
        String mcpEndpoint = "/mcp";

        String localUrl = String.format("%s://localhost:%s", protocol, port);
        String hostnameUrl = String.format("%s://%s:%s", protocol, hostAddress, port);

        String[] profiles = env.getActiveProfiles();
        String activeProfiles = (profiles.length == 0) ? "default" : String.join(", ", profiles);

        List<String> lines = new ArrayList<>();
        lines.add("");
        lines.add(banner);
        lines.add(DIVIDER);
        lines.add("    Application '" + appName + "' is running!");
        lines.add("");
        lines.add("    Access URLs:");
        lines.add("      Local:     " + localUrl);
        lines.add("      Hostname:  " + hostnameUrl);
        lines.add("");
        lines.add("    Profile(s): " + activeProfiles);
        lines.add("");
        lines.add("    External services:");
        lines.add("      Geocoding: " + probeUrl(WeatherApiEndpoints.GEOCODING_PROBE));
        lines.add("      Forecast:  " + probeUrl(WeatherApiEndpoints.FORECAST_PROBE));
        lines.add("");
        lines.add("    Actuator:");
        lines.add("      Health:     " + localUrl + "/actuator/health");
        lines.add("      Liveness:   " + localUrl + "/actuator/health/liveness");
        lines.add("      Readiness:  " + localUrl + "/actuator/health/readiness");
        lines.add("");
        lines.add("    Observability:");
        lines.add("      Logging:    Spring Boot defaults (logging.level.org.springframework.ai.mcp=INFO)");
        lines.add("");
        lines.add("    MCP tools:    " + describeMcpTools());
        lines.add("");
        lines.add("    MCP endpoint (Streamable HTTP):");
        lines.add("      POST  " + localUrl + mcpEndpoint);
        lines.add(DIVIDER);

        log.info("\n{}", String.join("\n", lines));
    }

    private String resolveHostAddress() {
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (UnknownHostException e) {
            log.debug("Could not resolve host name; using localhost fallback", e);
            return "localhost";
        }
    }

    String probeUrl(String url) {
        String baseUrl = url.substring(0, url.indexOf('?'));
        try {
            int status = executeProbe(url);

            if (status >= 200 && status < 300) {
                return baseUrl + " [Connected]";
            }

            return baseUrl + String.format(" [Warning (status=%d)]", status);
        } catch (Exception e) {
            log.debug("Probe failed for {}", url, e);

            return baseUrl + " [FAILED]";
        }
    }

    int executeProbe(String url) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout((int) PROBE_TIMEOUT.toMillis());
        factory.setReadTimeout((int) PROBE_TIMEOUT.toMillis());

        return RestClient.builder()
                .requestFactory(factory)
                .build()
                .get()
                .uri(url)
                .retrieve()
                .toBodilessEntity()
                .getStatusCode()
                .value();
    }

    private String describeMcpTools() {
        try {
            ToolCallbackProvider provider = toolCallbackProvider.getIfAvailable();
            if (provider == null) {
                return "[Warning (no ToolCallbackProvider)]";
            }
            ToolCallback[] tools = provider.getToolCallbacks();
            if (tools.length == 0) {
                return "[Connected] no tools registered";
            }
            String toolNames = Arrays.stream(tools)
                    .map(t -> t.getToolDefinition().name())
                    .collect(Collectors.joining(", "));
            return String.format("[Connected] %d tools: [%s]", tools.length, toolNames);
        } catch (Exception e) {
            log.debug("MCP tool listing failed", e);
            return "[FAILED]";
        }
    }
}
