package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record GeoResponse(List<GeoResult> results) {
}
