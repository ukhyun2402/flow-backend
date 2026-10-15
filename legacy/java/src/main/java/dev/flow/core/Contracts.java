package dev.flow.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

public final class Contracts {

    private Contracts() {}

    public static void check(JsonNode schema, JsonNode value) {
        if (schema == null || !schema.isObject()) throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "Invalid JSON Schema"
        );
        // Remote references are deliberately disabled: schemas must be self-contained.
        rejectRemote(schema);
        try {
            if (
                !JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(schema)
                    .validate(value)
                    .isEmpty()
            ) throw new FlowFault("VALIDATION_ERROR", 400, "Data does not satisfy its schema");
        } catch (FlowFault e) {
            throw e;
        } catch (RuntimeException e) {
            throw new FlowFault("VALIDATION_ERROR", 400, "Invalid JSON Schema");
        }
    }

    public static void rejectRemote(JsonNode n) {
        if (n.isObject()) {
            for (String key : new String[] { "$ref", "$dynamicRef", "$recursiveRef" })
                if (n.has(key) && !n.get(key).asText().startsWith("#")) throw new FlowFault(
                    "VALIDATION_ERROR",
                    400,
                    "Only local schema references are allowed"
                );
        }
        n.forEach(Contracts::rejectRemote);
    }
}
