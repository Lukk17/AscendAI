package com.lukk.ai.mcp.dto;

import com.fasterxml.jackson.annotation.JsonClassDescription;
import com.fasterxml.jackson.annotation.JsonPropertyDescription;

@JsonClassDescription("Represents the current weather conditions for a given location.")
public record WeatherResponse(@JsonPropertyDescription("The current temperature in degrees.") int temp,
                              @JsonPropertyDescription("A brief text description of the weather.") String weather) {

}

