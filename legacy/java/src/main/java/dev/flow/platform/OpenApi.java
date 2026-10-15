package dev.flow.platform;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import dev.flow.core.Flow;
import java.util.*;

final class OpenApi {

    private OpenApi() {}

    static JsonNode document(ObjectMapper json, Flow flow) {
        ObjectNode root = json.createObjectNode().put("openapi", "3.1.0");
        root.putObject("info")
            .put("title", flow.name())
            .put("version", Integer.toString(flow.revision()));
        ObjectNode components = root.putObject("components");
        ObjectNode schemas = components.putObject("schemas");
        schemas.set("Input", rebase(json, flow.inputSchema(), "#/components/schemas/Input"));
        schemas.set("Output", rebase(json, flow.outputSchema(), "#/components/schemas/Output"));
        Flow.Node start = flow
            .nodes()
            .stream()
            .filter(n -> n.type().equals("trigger.http"))
            .findFirst()
            .orElseThrow();
        String route = start.config().path("path").asText();
        ObjectNode operation = root
            .putObject("paths")
            .putObject(route)
            .putObject(start.config().path("method").asText().toLowerCase(Locale.ROOT));
        operation.put("operationId", flow.id());
        ArrayNode parameters = operation.putArray("parameters");
        Set<String> pathParameters = new HashSet<>();
        ObjectNode bodySchema = json.createObjectNode().put("type", "object");
        ObjectNode bodyProperties = bodySchema.putObject("properties");
        ArrayNode bodyRequired = bodySchema.putArray("required");
        var fields = start.config().path("input").fields();
        while (fields.hasNext()) {
            var field = fields.next();
            String source = field.getValue().path("source").asText();
            String[] parts = source.split("\\.", 2);
            if (parts.length != 2) continue;
            JsonNode fieldSchema = flow.inputSchema().path("properties").path(field.getKey());
            if (fieldSchema.isMissingNode()) fieldSchema = json
                .createObjectNode()
                .put("type", "string");
            JsonNode externalSchema = rebase(json, fieldSchema, "#/components/schemas/Input");
            if (Set.of("path", "query", "headers").contains(parts[0])) {
                ObjectNode p = parameters
                    .addObject()
                    .put("name", parts[1])
                    .put("in", parts[0].equals("headers") ? "header" : parts[0]);
                p.put(
                    "required",
                    parts[0].equals("path") || required(flow.inputSchema(), field.getKey())
                );
                p.set("schema", externalSchema);
                if (parts[0].equals("path")) pathParameters.add(parts[1]);
            } else if (parts[0].equals("body")) {
                ObjectNode target = bodyProperties;
                String[] bodyPath = parts[1].split("\\.");
                for (int i = 0; i < bodyPath.length - 1; i++) {
                    JsonNode existing = target.get(bodyPath[i]);
                    if (existing == null) {
                        ObjectNode obj = target.putObject(bodyPath[i]).put("type", "object");
                        target = obj.putObject("properties");
                    } else target = (ObjectNode) existing.path("properties");
                }
                target.set(bodyPath[bodyPath.length - 1], externalSchema);
                if (
                    bodyPath.length == 1 && required(flow.inputSchema(), field.getKey())
                ) bodyRequired.add(bodyPath[0]);
            }
        }
        var matcher = java.util.regex.Pattern.compile("\\{([^{}]+)}").matcher(route);
        while (matcher.find())
            if (pathParameters.add(matcher.group(1))) parameters
                .addObject()
                .put("name", matcher.group(1))
                .put("in", "path")
                .put("required", true)
                .putObject("schema")
                .put("type", "string");
        if (!bodyProperties.isEmpty()) operation
            .putObject("requestBody")
            .put("required", !bodyRequired.isEmpty())
            .putObject("content")
            .putObject("application/json")
            .set("schema", bodySchema);
        ObjectNode responses = operation.putObject("responses");
        for (Flow.Node n : flow.nodes()) {
            if (n.type().equals("response.http")) responses
                .putObject(n.config().path("status").asText())
                .put("description", "Flow response")
                .putObject("content")
                .putObject("application/json")
                .putObject("schema")
                .put("$ref", "#/components/schemas/Output");
            if (n.type().equals("error.raise")) responses
                .putObject(n.config().path("status").asText("400"))
                .put("description", n.config().path("code").asText("Business error"));
        }
        responses.putObject("default").put("description", "Sanitized execution error");
        if (flow.settings().path("authentication").asText().equals("bearer")) {
            components
                .putObject("securitySchemes")
                .putObject("bearerAuth")
                .put("type", "http")
                .put("scheme", "bearer");
            operation.putArray("security").addObject().putArray("bearerAuth");
        }
        return root;
    }

    private static boolean required(JsonNode schema, String name) {
        for (JsonNode r : schema.path("required")) if (r.asText().equals(name)) return true;
        return false;
    }

    private static JsonNode rebase(ObjectMapper json, JsonNode schema, String prefix) {
        if (schema.isObject()) {
            ObjectNode out = json.createObjectNode();
            schema.fields().forEachRemaining(e -> {
                if (
                    Set.of("$ref", "$dynamicRef").contains(e.getKey()) &&
                    e.getValue().asText().startsWith("#")
                ) out.put(e.getKey(), prefix + e.getValue().asText().substring(1));
                else out.set(e.getKey(), rebase(json, e.getValue(), prefix));
            });
            return out;
        }
        if (schema.isArray()) {
            ArrayNode out = json.createArrayNode();
            schema.forEach(n -> out.add(rebase(json, n, prefix)));
            return out;
        }
        return schema;
    }
}
