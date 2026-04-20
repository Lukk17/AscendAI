plugins {
    java
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.spring.dependency.management)
    alias(libs.plugins.springdoc.openapi)
}

group = "com.lukk"
version = "0.0.1"

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(21)
    }
}

configurations {
    compileOnly {
        extendsFrom(configurations.annotationProcessor.get())
    }
}

repositories {
    mavenCentral()
    maven { url = uri("https://repo.spring.io/milestone") }
}

dependencyManagement {
    imports {
        mavenBom(libs.spring.ai.bom.get().toString())
        mavenBom(libs.aws.sdk.bom.get().toString())
    }
}

dependencies {
    // Spring Boot
    implementation(libs.spring.boot.starter.web)
    implementation(libs.spring.boot.starter.webflux)
    implementation(libs.spring.boot.starter.data.redis)
    implementation(libs.spring.boot.starter.oauth2.client)
    implementation(libs.spring.boot.starter.data.jdbc)
    implementation(libs.spring.boot.starter.integration)

    // Spring AI (versions from Spring AI BOM)
    implementation(libs.spring.ai.starter.model.openai)
    implementation(libs.spring.ai.starter.model.anthropic)
    implementation(libs.spring.ai.starter.mcp.client.webflux)
    implementation(libs.spring.ai.starter.vector.store.qdrant)
    implementation(libs.spring.ai.advisors.vector.store)

    // Spring Integration
    implementation(libs.spring.integration.file)
    implementation(libs.spring.integration.jdbc)
    implementation(libs.spring.integration.aws)

    // Database
    implementation(libs.postgresql)
    implementation(libs.liquibase.core)

    // AWS SDK (version from AWS BOM)
    implementation(libs.aws.sdk.s3)

    // Standalone libraries
    implementation(libs.qdrant.client)
    implementation(libs.commonmark)
    implementation(libs.pdfbox)

    // Springdoc OpenAPI
    implementation(libs.springdoc.openapi.starter.webmvc.ui)

    // Lombok
    compileOnly(libs.lombok)
    annotationProcessor(libs.lombok)

    // Dev tools
    developmentOnly(libs.spring.boot.devtools)

    // Test
    testImplementation(libs.spring.boot.starter.test)
    testRuntimeOnly(libs.junit.platform.launcher)
    testRuntimeOnly(libs.h2)
}

tasks.withType<Test> {
    useJUnitPlatform()
}