package com.lukk.ascend.ai.agent.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;

import static org.assertj.core.api.Assertions.assertThat;

class S3EndpointPropertiesTest {

    private static final String HOST_ADDRESS = "http://localhost:4566";
    private static final String CONTAINER_ADDRESS = "http://host.docker.internal:4566";

    @Test
    @DisplayName("A host run reads both object store addresses from OBJECT_STORE_S3_PUBLIC_ENDPOINT")
    void hostRun_PublicEndpointSet_ResolvesBothAddressesFromIt() {
        // given
        try (ConfigurableApplicationContext context = startContext(
                new String[]{},
                "OBJECT_STORE_S3_ENDPOINT=" + CONTAINER_ADDRESS,
                "OBJECT_STORE_S3_PUBLIC_ENDPOINT=" + HOST_ADDRESS)) {

            // when
            Environment environment = context.getEnvironment();

            // then
            assertThat(environment.getProperty("app.s3.endpoint")).isEqualTo(HOST_ADDRESS);
            assertThat(environment.getProperty("app.s3.public-endpoint")).isEqualTo(HOST_ADDRESS);
        }
    }

    @Test
    @DisplayName("The docker profile reads the container and public object store addresses from their own variables")
    void dockerProfile_BothEndpointsSet_ResolvesEachFromItsOwnVariable() {
        // given
        try (ConfigurableApplicationContext context = startContext(
                new String[]{"docker"},
                "OBJECT_STORE_S3_ENDPOINT=" + CONTAINER_ADDRESS,
                "OBJECT_STORE_S3_PUBLIC_ENDPOINT=" + HOST_ADDRESS)) {

            // when
            Environment environment = context.getEnvironment();

            // then
            assertThat(environment.getProperty("app.s3.endpoint")).isEqualTo(CONTAINER_ADDRESS);
            assertThat(environment.getProperty("app.s3.public-endpoint")).isEqualTo(HOST_ADDRESS);
        }
    }

    private ConfigurableApplicationContext startContext(String[] profiles, String... properties) {
        return new SpringApplicationBuilder(EmptyConfiguration.class)
                .web(WebApplicationType.NONE)
                .profiles(profiles)
                .properties(properties)
                .run();
    }

    @Configuration(proxyBeanMethods = false)
    static class EmptyConfiguration {
    }
}
