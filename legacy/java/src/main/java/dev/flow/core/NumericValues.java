package dev.flow.core;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import java.math.*;

/** Wire representation is independent of JavaScript's floating point limits. */
public final class NumericValues {

    private NumericValues() {}

    public static JsonNode encode(ObjectMapper json, BigDecimal value) {
        if (value.precision() > 512 || Math.abs((long) value.scale()) > 1000) throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "Numeric value exceeds precision limits"
        );
        if (value.scale() <= 0) {
            BigInteger integer = value.toBigIntegerExact();
            if (
                integer.abs().compareTo(BigInteger.valueOf(9007199254740991L)) <= 0
            ) return BigIntegerNode.valueOf(integer);
            return json.createObjectNode().put("type", "integer").put("value", integer.toString());
        }
        return json.createObjectNode().put("type", "decimal").put("value", value.toPlainString());
    }

    public static boolean isNumeric(JsonNode n) {
        return (
            n.isNumber() ||
            (n.isObject() &&
                n.path("value").isTextual() &&
                java.util.Set.of("decimal", "integer").contains(n.path("type").asText()))
        );
    }

    public static BigDecimal parse(String text) {
        if (text.length() > 256) throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "Numeric literal exceeds limits"
        );
        try {
            BigDecimal d = new BigDecimal(text);
            if (
                Math.abs((long) d.scale()) > 1000 || d.precision() > 256
            ) throw new NumberFormatException();
            return d;
        } catch (NumberFormatException ex) {
            throw new FlowFault("VALIDATION_ERROR", 400, "Invalid numeric literal");
        }
    }

    public static BigDecimal number(JsonNode n) {
        if (n.isNumber()) return parse(n.asText());
        if (isNumeric(n)) {
            String text = n.get("value").textValue();
            if (
                n.path("type").asText().equals("integer") && !text.matches("-?[0-9]+")
            ) throw new FlowFault("VALIDATION_ERROR", 400, "Invalid typed integer");
            return parse(text);
        }
        throw new FlowFault("VALIDATION_ERROR", 400, "Number required");
    }
}
