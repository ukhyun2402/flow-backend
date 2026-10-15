package dev.flow.core;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

public record Flow(
    String specVersion,
    String id,
    int revision,
    String name,
    JsonNode inputSchema,
    JsonNode outputSchema,
    JsonNode resources,
    List<Node> nodes,
    List<Edge> edges,
    JsonNode settings,
    JsonNode ui
) {
    public record Node(String id, String type, String name, JsonNode config) {}

    public record Edge(String from, String port, String to) {}
}
