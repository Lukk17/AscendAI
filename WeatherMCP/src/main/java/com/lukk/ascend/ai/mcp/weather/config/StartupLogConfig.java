package com.lukk.ascend.ai.mcp.weather.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.context.event.EventListener;
import org.springframework.core.env.Environment;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

@Component
@Slf4j
public class StartupLogConfig {

    private static final String BANNER =
            "██╗    ██╗███████╗ █████╗ ████████╗██╗  ██╗███████╗██████╗     ███╗   ███╗ ██████╗██████╗ \n" +
            "██║    ██║██╔════╝██╔══██╗╚══██╔══╝██║  ██║██╔════╝██╔══██╗    ████╗ ████║██╔════╝██╔══██╗\n" +
            "██║ █╗ ██║█████╗  ███████║   ██║   ███████║█████╗  ██████╔╝    ██╔████╔██║██║     ██████╔╝\n" +
            "██║███╗██║██╔══╝  ██╔══██║   ██║   ██╔══██║██╔══╝  ██╔══██╗    ██║╚██╔╝██║██║     ██╔═══╝ \n" +
            "╚███╔███╔╝███████╗██║  ██║   ██║   ██║  ██║███████╗██║  ██║    ██║ ╚═╝ ██║╚██████╗██║     \n" +
            " ╚══╝╚══╝ ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝    ╚═╝     ╚═╝ ╚═════╝╚═╝     ";

    private static final String DIVIDER = "----------------------------------------------------------";

    private static final Duration PROBE_TIMEOUT = Duration.ofSeconds(2);
    private static final String GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1";
    private static final String FORECAST_URL = "https://api.open-meteo.com/v1/forecast?latitude=52&longitude=13&current_weather=true";

    private final Environment env;
    private final ObjectProvider<ToolCallbackProvider> toolCallbackProvider;

    public StartupLogConfig(Environment env, ObjectProvider<ToolCallbackProvider> toolCallbackProvider) {
        this.env = env;
        this.toolCallbackProvider = toolCallbackProvider;
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
        String sseEndpoint = env.getProperty("spring.ai.mcp.server.sse-message-endpoint", "/mcp");

        String localUrl = String.format("%s://localhost:%s", protocol, port);
        String hostnameUrl = String.format("%s://%s:%s", protocol, hostAddress, port);

        String[] profiles = env.getActiveProfiles();
        String activeProfiles = (profiles.length == 0) ? "default" : String.join(", ", profiles);

        List<String> lines = new ArrayList<>();
        lines.add("");
        lines.add(BANNER);
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
        lines.add("      Geocoding: " + probeUrl(GEOCODING_URL));
        lines.add("      Forecast:  " + probeUrl(FORECAST_URL));
        lines.add("");
        lines.add("    Actuator:");
        lines.add("      Health:     " + localUrl + "/actuator/health");
        lines.add("      Liveness:   " + localUrl + "/actuator/health/liveness");
        lines.add("      Readiness:  " + localUrl + "/actuator/health/readiness");
        lines.add("");
        lines.add("    Observability:");
        lines.add("      Logging:    Spring Boot defaults (logging.level.org.springframework.ai.mcp=DEBUG)");
        lines.add("");
        lines.add("    MCP tools:    " + describeMcpTools());
        lines.add("");
        lines.add("    MCP ENDPOINT (SSE):");
        lines.add("      GET   " + localUrl + sseEndpoint);
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

    private String probeUrl(String url) {
        String baseUrl = url.substring(0, url.indexOf('?'));
        try {
            SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
            factory.setConnectTimeout((int) PROBE_TIMEOUT.toMillis());
            factory.setReadTimeout((int) PROBE_TIMEOUT.toMillis());
            int status = RestClient.builder()
                    .requestFactory(factory)
                    .build()
                    .get()
                    .uri(url)
                    .retrieve()
                    .toBodilessEntity()
                    .getStatusCode()
                    .value();
            if (status >= 200 && status < 300) {
                return baseUrl + " [Connected]";
            }
            return baseUrl + String.format(" [Warning (status=%d)]", status);
        } catch (Exception e) {
            log.debug("Probe failed for {}", url, e);
            return baseUrl + " [FAILED]";
        }
    }

    private String describeMcpTools() {
        try {
            ToolCallbackProvider provider = toolCallbackProvider.getIfAvailable();
            if (provider == null) {
                return "[Warning (no ToolCallbackProvider)]";
            }
            ToolCallback[] tools = provider.getToolCallbacks();
            if (tools == null || tools.length == 0) {
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
