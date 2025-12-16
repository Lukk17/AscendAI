package com.lukk.ai.orchestrator.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.net.UnknownHostException;

@Component
public class StartupLogConfig implements ApplicationListener<ApplicationReadyEvent> {

    private static final Logger log = LoggerFactory.getLogger(StartupLogConfig.class);
    private final Environment env;

    public StartupLogConfig(Environment env) {
        this.env = env;
    }

    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        String serverPort = env.getProperty("local.server.port");
        if (serverPort == null) {
            serverPort = env.getProperty("server.port");
        }

        String contextPath = env.getProperty("server.servlet.context-path");
        if (contextPath == null) {
            contextPath = "";
        }
        String hostAddress = "localhost";
        try {
            hostAddress = InetAddress.getLocalHost().getHostAddress();
        } catch (UnknownHostException e) {
            log.warn("The host name could not be determined, using `localhost` as fallback");
        }

        String protocol = "http";
        if (env.getProperty("server.ssl.key-store") != null) {
            protocol = "https";
        }

        String appName = env.getProperty("spring.application.name");
        if (appName == null) {
            appName = "AscendAI Orchestrator";
        }

        String mainPromptUrl = String.format("%s://localhost:%s%s/prompt", protocol, serverPort, contextPath);

        String[] profiles = env.getActiveProfiles();
        String activeProfiles = (profiles.length == 0) ? "default" : String.join(", ", profiles);

        log.info("\n" +
                        "    _                            _    _    ___ \n" +
                        "   /_\\  ___  ___ ___ _ __   __| |  /_\\  |_ _|\n" +
                        "  / _ \\/ __|/ __/ _ \\ '_ \\ / _` | / _ \\  | | \n" +
                        " /_/ \\_\\___|\\___\\___/ .__/ \\__,_|/_/ \\_\\|___|\n" +
                        "                    |_|                      \n" +
                        "\n" +
                        "----------------------------------------------------------\n" +
                        "\tApplication '{}' is running! Access URLs:\n" +
                        "\tLocal: \t\t{}://localhost:{}{}\n" +
                        "\tExternal: \t{}://{}:{}{}\n" +
                        "\tProfile(s): \t{}\n" +
                        "\n" +
                        "\tMAIN PROMPT ENDPOINT:\n" +
                        "\tPOST \t\t{}\n" +
                        "----------------------------------------------------------",
                appName,
                protocol, serverPort, contextPath,
                protocol, hostAddress, serverPort, contextPath,
                activeProfiles,
                mainPromptUrl);
    }
}
