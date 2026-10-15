package dev.flow.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.*;
import java.math.BigDecimal;
import java.math.MathContext;
import java.util.*;

/** Bounded, strict, declarative expressions. No script evaluation. */
public final class Expressions {

    private static final ObjectMapper JSON = new ObjectMapper();
    private int remaining = 10000;
    private final JsonNode context;

    public Expressions(JsonNode context) {
        this.context = context;
    }

    public JsonNode evaluate(JsonNode expr) {
        return eval(expr, 0);
    }

    private JsonNode eval(JsonNode e, int depth) {
        if (--remaining < 0 || depth > 64) throw fault("Expression limit exceeded");
        if (e == null) return NullNode.instance;
        if (e.isArray()) {
            ArrayNode a = JSON.createArrayNode();
            e.forEach(v -> a.add(eval(v, depth + 1)));
            return a;
        }
        if (!e.isObject()) return e;
        if (e.has("literal")) return e.get("literal");
        if (e.has("ref")) {
            JsonNode value = context;
            for (String part : e.get("ref").asText().split("\\.")) {
                value = value.path(part);
                if (value.isMissingNode()) throw fault("Undefined reference");
            }
            return value;
        }
        if (!e.has("op")) {
            ObjectNode obj = JSON.createObjectNode();
            e.fields().forEachRemaining(f -> obj.set(f.getKey(), eval(f.getValue(), depth + 1)));
            return obj;
        }
        List<JsonNode> a = new ArrayList<>();
        e.path("args").forEach(v -> a.add(eval(v, depth + 1)));
        try {
            return switch (e.path("op").asText()) {
                case "eq", "ne" -> {
                    arity(a, 2);
                    boolean equal =
                        NumericValues.isNumeric(a.get(0)) && NumericValues.isNumeric(a.get(1))
                            ? number(a.get(0)).compareTo(number(a.get(1))) == 0
                            : a.get(0).equals(a.get(1));
                    yield BooleanNode.valueOf(e.get("op").asText().equals("eq") == equal);
                }
                case "gt", "gte", "lt", "lte" -> {
                    arity(a, 2);
                    int c = number(a.get(0)).compareTo(number(a.get(1)));
                    yield BooleanNode.valueOf(
                        switch (e.get("op").asText()) {
                            case "gt" -> c > 0;
                            case "gte" -> c >= 0;
                            case "lt" -> c < 0;
                            default -> c <= 0;
                        }
                    );
                }
                case "and" -> {
                    boolean b = true;
                    for (JsonNode n : a) b &= bool(n);
                    yield BooleanNode.valueOf(b);
                }
                case "or" -> {
                    boolean b = false;
                    for (JsonNode n : a) b |= bool(n);
                    yield BooleanNode.valueOf(b);
                }
                case "not" -> {
                    arity(a, 1);
                    yield BooleanNode.valueOf(!bool(a.get(0)));
                }
                case "isNull", "notNull" -> {
                    arity(a, 1);
                    yield BooleanNode.valueOf(
                        a.get(0).isNull() == e.get("op").asText().equals("isNull")
                    );
                }
                case "coalesce" -> a.stream()
                    .filter(v -> !v.isNull())
                    .findFirst()
                    .orElse(NullNode.instance);
                case "add", "subtract", "multiply", "divide" -> {
                    arity(a, 2);
                    BigDecimal x = number(a.get(0)),
                        y = number(a.get(1));
                    yield NumericValues.encode(
                        JSON,
                        switch (e.get("op").asText()) {
                            case "add" -> x.add(y);
                            case "subtract" -> x.subtract(y);
                            case "multiply" -> x.multiply(y);
                            default -> x.divide(y, MathContext.DECIMAL128);
                        }
                    );
                }
                case "concat" -> {
                    StringBuilder s = new StringBuilder();
                    for (JsonNode n : a) s.append(string(n));
                    yield TextNode.valueOf(s.toString());
                }
                case "trim" -> {
                    arity(a, 1);
                    yield TextNode.valueOf(string(a.get(0)).trim());
                }
                case "contains" -> {
                    arity(a, 2);
                    yield BooleanNode.valueOf(string(a.get(0)).contains(string(a.get(1))));
                }
                case "toNumber" -> {
                    arity(a, 1);
                    yield NumericValues.encode(JSON, NumericValues.parse(string(a.get(0))));
                }
                case "toString" -> {
                    arity(a, 1);
                    if (
                        a.get(0).isObject() && NumericValues.isNumeric(a.get(0))
                    ) yield TextNode.valueOf(number(a.get(0)).toPlainString());
                    if (!a.get(0).isValueNode() || a.get(0).isNull()) throw fault(
                        "Scalar required"
                    );
                    yield TextNode.valueOf(a.get(0).asText());
                }
                case "toDateTime" -> {
                    arity(a, 1);
                    try {
                        yield TextNode.valueOf(
                            java.time.OffsetDateTime.parse(string(a.get(0)))
                                .toInstant()
                                .toString()
                        );
                    } catch (java.time.DateTimeException ex) {
                        throw fault("ISO-8601 date-time with explicit offset required");
                    }
                }
                default -> throw fault("Unknown operator");
            };
        } catch (ArithmeticException | IndexOutOfBoundsException | NumberFormatException ex) {
            throw fault("Invalid expression arguments");
        }
    }

    public static boolean bool(JsonNode n) {
        if (!n.isBoolean()) throw fault("Boolean required");
        return n.booleanValue();
    }

    private static BigDecimal number(JsonNode n) {
        return NumericValues.number(n);
    }

    private static String string(JsonNode n) {
        if (!n.isTextual()) throw fault("String required");
        return n.textValue();
    }

    private static void arity(List<?> a, int n) {
        if (a.size() != n) throw fault("Invalid operator arity");
    }

    private static FlowFault fault(String s) {
        return new FlowFault("VALIDATION_ERROR", 400, s);
    }
}
