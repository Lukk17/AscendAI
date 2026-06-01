# syntax=docker/dockerfile:1.7

# ─── Build stage ───
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /build

# Pre-cache dependencies in their own layer so code-only changes reuse it.
COPY gradlew gradlew.bat ./
COPY gradle/ gradle/
COPY build.gradle.kts settings.gradle.kts ./
RUN chmod +x gradlew && ./gradlew --no-daemon dependencies

# Compile the application.
COPY src/ src/
RUN ./gradlew --no-daemon bootJar -x test

# ─── Runtime stage ───
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

RUN addgroup -S app && adduser -S app -G app
COPY --from=builder --chown=app:app /build/build/libs/*.jar /app/app.jar
USER app

EXPOSE 9917

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:9917/actuator/health || exit 1

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
