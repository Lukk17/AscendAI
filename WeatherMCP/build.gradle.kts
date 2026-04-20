plugins {
    java
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.spring.dependency.management)
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
}

dependencyManagement {
    imports {
        mavenBom(libs.spring.ai.bom.get().toString())
    }
}

dependencies {
    // MCP server starter for SSE
    implementation(libs.spring.boot.starter.web)
    implementation(libs.spring.ai.starter.mcp.server.webmvc)

    // MCP server starter for STDIO (alternative, disabled)
    // implementation("org.springframework.boot:spring-boot-starter")
    // implementation("org.springframework.ai:spring-ai-starter-mcp-server")

    compileOnly(libs.lombok)
    annotationProcessor(libs.lombok)

    developmentOnly(libs.spring.boot.devtools)

    testImplementation(libs.spring.boot.starter.test)
    testRuntimeOnly(libs.junit.platform.launcher)
}

tasks.withType<Test> {
    useJUnitPlatform()
}

// Disable the plain jar to avoid the *.jar conflict
tasks.jar {
    enabled = false
}