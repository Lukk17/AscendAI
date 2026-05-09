plugins {
    java
    jacoco
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.spring.dependency.management)
    alias(libs.plugins.springdoc.openapi)
}

jacoco {
    toolVersion = libs.versions.jacoco.get()
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
        mavenBom(libs.testcontainers.bom.get().toString())
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
    implementation(libs.tika.core)

    // Security
    implementation(libs.spring.boot.starter.security)

    // Springdoc OpenAPI
    implementation(libs.springdoc.openapi.starter.webmvc.ui)

    // Lombok
    compileOnly(libs.lombok)
    annotationProcessor(libs.lombok)

    // Dev tools
    developmentOnly(libs.spring.boot.devtools)

    // Test
    testImplementation(libs.spring.boot.starter.test)
    testImplementation(libs.spring.boot.testcontainers)
    testImplementation(libs.testcontainers.junit)
    testImplementation(libs.testcontainers.postgresql)
    testImplementation(libs.testcontainers.qdrant)
    testImplementation(libs.testcontainers.minio)
    testRuntimeOnly(libs.junit.platform.launcher)
    testRuntimeOnly(libs.h2)
}

tasks.test {
    useJUnitPlatform {
        excludeTags("integration")
    }
    finalizedBy(tasks.jacocoTestReport)
}

tasks.register<Test>("integrationTest") {
    description = "Runs integration tests (@Tag(\"integration\")). Requires Docker to be running for Testcontainers."
    group = "verification"
    useJUnitPlatform {
        includeTags("integration")
    }
    shouldRunAfter(tasks.test)
    testClassesDirs = sourceSets["test"].output.classesDirs
    classpath = sourceSets["test"].runtimeClasspath
    // Optional override for environments where Testcontainers' auto-detection picks the wrong pipe.
    // When unset (default), Testcontainers detects from the active Docker context.
    //   ./gradlew integrationTest -Pdocker.host=npipe:////./pipe/docker_engine
    (project.findProperty("docker.host") as String?)?.let {
        environment("DOCKER_HOST", it)
    }
    // Pin the Docker API version so docker-java doesn't fall back to ancient 1.32
    // when Docker Desktop's proxy garbles the _ping response. Daemon requires >=1.40.
    environment("DOCKER_API_VERSION", "1.43")
    finalizedBy(tasks.jacocoTestReport)
}

tasks.jacocoTestReport {
    executionData(fileTree(layout.buildDirectory).include("/jacoco/test.exec", "/jacoco/integrationTest.exec"))
    reports {
        xml.required.set(true)
        html.required.set(true)
    }
}

tasks.jacocoTestCoverageVerification {
    violationRules {
        rule {
            limit {
                counter = "INSTRUCTION"
                value = "COVEREDRATIO"
                minimum = "0.80".toBigDecimal()
            }
        }
    }
}