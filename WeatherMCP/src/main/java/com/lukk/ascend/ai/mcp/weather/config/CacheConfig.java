package com.lukk.ascend.ai.mcp.weather.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;

@Configuration
public class CacheConfig {

    public static final String GEOCODING_SINGLE_CACHE = "geocoding-single";
    public static final String GEOCODING_MULTI_CACHE = "geocoding-multi";
    public static final String CURRENT_WEATHER_CACHE = "current-weather";
    public static final String FORECAST_CACHE = "forecast";
    public static final String HISTORICAL_WEATHER_CACHE = "historical-weather";
    public static final String AIR_QUALITY_CACHE = "air-quality";

    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager(
                GEOCODING_SINGLE_CACHE,
                GEOCODING_MULTI_CACHE,
                CURRENT_WEATHER_CACHE,
                FORECAST_CACHE,
                HISTORICAL_WEATHER_CACHE,
                AIR_QUALITY_CACHE
        );
        manager.registerCustomCache(GEOCODING_SINGLE_CACHE, buildCache(Duration.ofHours(24), 1000));
        manager.registerCustomCache(GEOCODING_MULTI_CACHE, buildCache(Duration.ofHours(24), 1000));
        manager.registerCustomCache(CURRENT_WEATHER_CACHE, buildCache(Duration.ofMinutes(10), 2000));
        manager.registerCustomCache(FORECAST_CACHE, buildCache(Duration.ofMinutes(30), 1000));
        manager.registerCustomCache(HISTORICAL_WEATHER_CACHE, buildCache(Duration.ofHours(24), 500));
        manager.registerCustomCache(AIR_QUALITY_CACHE, buildCache(Duration.ofMinutes(15), 1000));

        return manager;
    }

    private static com.github.benmanes.caffeine.cache.Cache<Object, Object> buildCache(Duration ttl, int maxSize) {
        return Caffeine.newBuilder()
                .expireAfterWrite(ttl)
                .maximumSize(maxSize)
                .recordStats()
                .build();
    }
}
