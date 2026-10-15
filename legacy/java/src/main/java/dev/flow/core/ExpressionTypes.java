package dev.flow.core;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;

/** Conservative static typing; unknown SQL output must supply an outputSchema for strict checks. */
public final class ExpressionTypes {

    private ExpressionTypes() {}

    public static String infer(
        JsonNode e,
        Flow flow,
        Map<String, Flow.Node> nodes,
        Set<String> visiting,
        int depth
    ) {
        if (depth > 64) throw invalid("Expression nesting exceeds 64");
        if (e == null || e.isNull()) return "null";
        if (e.isBoolean()) return "boolean";
        if (e.isNumber()) return e.isIntegralNumber() ? "integer" : "number";
        if (e.isTextual()) return "string";
        if (e.isArray()) {
            for (JsonNode n : e) infer(n, flow, nodes, visiting, depth + 1);
            return "array";
        }
        if (e.has("literal")) return NumericValues.isNumeric(e.get("literal"))
            ? "number"
            : inferLiteral(e.get("literal"));
        if (e.isObject() && NumericValues.isNumeric(e)) return "number";
        if (e.has("ref")) {
            String[] path = e.get("ref").asText().split("\\.");
            if (path[0].equals("context")) return "string";
            if (path[0].equals("input")) return schemaPath(flow.inputSchema(), path, 1);
            if (path[0].equals("nodes") && path.length >= 3) {
                Flow.Node source = nodes.get(path[1]);
                if (source == null) return "unknown";
                JsonNode schema = source.config().get("outputSchema");
                if (schema != null) return schemaPath(schema, path, 3);
                if (source.type().equals("transform") && visiting.add(source.id())) {
                    JsonNode mapping = source.config().path("mapping");
                    for (int i = 3; i < path.length; i++) {
                        if (mapping.has("ref") || mapping.has("op")) return "unknown";
                        mapping = mapping.path(path[i]);
                    }
                    return infer(mapping, flow, nodes, visiting, depth + 1);
                }
            }
            return "unknown";
        }
        if (!e.has("op")) {
            e.forEach(n -> infer(n, flow, nodes, new HashSet<>(visiting), depth + 1));
            return "object";
        }
        String op = e.path("op").asText();
        JsonNode args = e.path("args");
        if (!args.isArray()) throw invalid("Operator args must be an array");
        List<String> types = new ArrayList<>();
        for (JsonNode a : args)
            types.add(infer(a, flow, nodes, new HashSet<>(visiting), depth + 1));
        return switch (op) {
            case "eq", "ne" -> {
                arity(types, 2);
                yield "boolean";
            }
            case "gt", "gte", "lt", "lte" -> {
                arity(types, 2);
                require(types, "number");
                yield "boolean";
            }
            case "and", "or" -> {
                if (types.isEmpty()) throw invalid("Logical operator needs arguments");
                require(types, "boolean");
                yield "boolean";
            }
            case "not" -> {
                arity(types, 1);
                require(types, "boolean");
                yield "boolean";
            }
            case "isNull", "notNull" -> {
                arity(types, 1);
                yield "boolean";
            }
            case "coalesce" -> types
                .stream()
                .filter(t -> !t.equals("null"))
                .findFirst()
                .orElse("null");
            case "add", "subtract", "multiply", "divide" -> {
                arity(types, 2);
                require(types, "number");
                yield "number";
            }
            case "trim" -> {
                arity(types, 1);
                require(types, "string");
                yield "string";
            }
            case "concat" -> {
                require(types, "string");
                yield "string";
            }
            case "contains" -> {
                arity(types, 2);
                require(types, "string");
                yield "boolean";
            }
            case "toNumber" -> {
                arity(types, 1);
                require(types, "string");
                yield "number";
            }
            case "toString" -> {
                arity(types, 1);
                yield "string";
            }
            case "toDateTime" -> {
                arity(types, 1);
                require(types, "string");
                yield "string";
            }
            default -> throw invalid("Unknown expression operator: " + op);
        };
    }

    public static boolean compatible(String actual, String expected) {
        return (
            actual.equals("unknown") ||
            expected.equals("unknown") ||
            actual.equals(expected) ||
            (actual.equals("integer") && expected.equals("number"))
        );
    }

    private static String schemaPath(JsonNode schema, String[] path, int start) {
        if (schema == null) return "unknown";
        for (int i = start; i < path.length; i++) {
            JsonNode next = schema.path("properties").path(path[i]);
            if (next.isMissingNode()) throw invalid("Reference is not declared in schema");
            schema = next;
        }
        return schema.path("type").isTextual() ? schema.get("type").asText() : "unknown";
    }

    private static String inferLiteral(JsonNode n) {
        return n.isNull()
            ? "null"
            : n.isObject()
              ? "object"
              : n.isArray()
                ? "array"
                : n.isBoolean()
                  ? "boolean"
                  : n.isNumber()
                    ? "number"
                    : "string";
    }

    private static void require(List<String> types, String expected) {
        if (types.stream().anyMatch(t -> !compatible(t, expected))) throw invalid(
            "Operator expects " + expected + " arguments"
        );
    }

    private static void arity(List<String> types, int size) {
        if (types.size() != size) throw invalid("Invalid operator arity");
    }

    private static FlowFault invalid(String message) {
        return new FlowFault("VALIDATION_ERROR", 400, message);
    }
}
