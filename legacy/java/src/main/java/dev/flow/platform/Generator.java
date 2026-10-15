package dev.flow.platform;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import dev.flow.core.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "flow.mode", havingValue = "platform", matchIfMissing = true)
public class Generator {

    private final ObjectMapper json;
    private final Validator validator;

    public Generator(ObjectMapper json, Validator validator) {
        this.json = json;
        this.validator = validator;
    }

    public byte[] generate(Flow flow) throws Exception {
        validator.plan(flow);
        if (
            !Set.of("public", "bearer").contains(flow.settings().path("authentication").asText())
        ) throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "Choose an explicit API authentication policy"
        );
        TreeMap<String, byte[]> files = new TreeMap<>();
        var resources = new PathMatchingResourcePatternResolver().getResources(
            "classpath*:generation-template/**/*"
        );
        for (var resource : resources) {
            String url = resource.getURL().toString();
            String name = url.substring(url.indexOf("generation-template/") + 20);
            if (name.endsWith(".java") || name.equals("pom.xml")) try (
                var in = resource.getInputStream()
            ) {
                files.put(name, in.readAllBytes());
            }
        }
        if (!files.containsKey("pom.xml")) throw new IllegalStateException(
            "Generation templates missing"
        );
        // Sort object keys for reproducibility; UI data never affects execution artifacts.
        ObjectNode canonical = (ObjectNode) json.valueToTree(flow);
        canonical.remove("ui");
        byte[] flowBytes = json.writeValueAsBytes(sorted(canonical));
        files.put("flows/" + flow.id() + ".json", flowBytes);
        ObjectNode manifest = json
            .createObjectNode()
            .put("generatorVersion", "0.1.0")
            .put("runtimeVersion", "0.1.0")
            .put("flowId", flow.id())
            .put("revision", flow.revision())
            .put(
                "flowHash",
                HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(flowBytes))
            );
        ObjectNode hashes = manifest.putObject("files");
        for (var entry : files.entrySet())
            hashes.put(
                entry.getKey(),
                HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(entry.getValue())
                )
            );
        files.put("schemas/input.json", json.writeValueAsBytes(sorted(flow.inputSchema())));
        files.put("schemas/output.json", json.writeValueAsBytes(sorted(flow.outputSchema())));
        try (var in = Validator.class.getResourceAsStream("/flow.schema.json")) {
            files.put("src/main/resources/flow.schema.json", in.readAllBytes());
        }
        files.put("openapi.json", json.writeValueAsBytes(openapi(flow)));
        put(
            files,
            "src/main/resources/application.properties",
            "flow.mode=runtime\nserver.port=${PORT:8080}\nserver.error.include-message=never\nserver.error.include-stacktrace=never\n"
        );
        put(
            files,
            "Dockerfile",
            "FROM maven:3.9.11-eclipse-temurin-21 AS build\nWORKDIR /app\nCOPY pom.xml .\nCOPY src src\nRUN mvn -B package -DskipTests\nFROM eclipse-temurin:21-jre\nWORKDIR /app\nCOPY --from=build /app/target/flow-platform-0.1.0.jar app.jar\nCOPY flows flows\nUSER 10001\nEXPOSE 8080\nENTRYPOINT [\"java\",\"-jar\",\"app.jar\"]\n"
        );
        put(
            files,
            ".env.example",
            "FLOW_RUNTIME_TOKEN=replace-with-a-long-random-token\nFLOW_DATABASE_CONFIG=/run/config/databases.json\n"
        );
        put(
            files,
            "dependency-manifest",
            "Java >=17; Spring Boot 3.5.16; exact dependencies: pom.xml\nTibero JDBC must be supplied separately; redistribution license must be verified.\n"
        );
        put(
            files,
            "config/databases.example.json",
            "{\"main\":{\"vendor\":\"mysql\",\"jdbcUrl\":\"jdbc:mysql://db:3306/app\",\"username\":\"app\",\"passwordSecretRef\":\"APP_DB_PASSWORD\"}}\n"
        );
        put(
            files,
            "README.md",
            "# Generated Flow Server\n\nBuild: `mvn package` (JDK 17+, Maven 3.6.3+). Run from this directory: `java -jar target/flow-platform-0.1.0.jar`.\n\nSet FLOW_RUNTIME_TOKEN for bearer authentication. Set FLOW_DATABASE_CONFIG to an external JSON configuration file and provide its passwordSecretRef as an environment variable. No platform management APIs are included.\n\nDocker: `docker build -t generated-flow .`. Mount DB configuration read-only; inject secrets at runtime. Tibero requires an externally supplied vendor JDBC JAR and classpath launch (see platform support matrix).\n\nKeep extensions in `extensions/`; export into a fresh directory and merge only generated paths. Changes to generated Java are not imported into Flow.\n"
        );
        put(files, "extensions/.gitkeep", "");
        put(
            files,
            "tests/README.md",
            "Run API contract checks against openapi.json and schemas/. Integration against the target DB remains required.\n"
        );
        hashes.removeAll();
        for (var entry : files.entrySet())
            hashes.put(
                entry.getKey(),
                HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(entry.getValue())
                )
            );
        files.put("generation-manifest.json", json.writeValueAsBytes(sorted(manifest)));
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            for (var entry : files.entrySet()) {
                ZipEntry e = new ZipEntry(entry.getKey());
                e.setTime(0);
                zip.putNextEntry(e);
                zip.write(entry.getValue());
                zip.closeEntry();
            }
        }
        return bytes.toByteArray();
    }

    private void put(Map<String, byte[]> files, String name, String text) {
        files.put(name, text.getBytes(StandardCharsets.UTF_8));
    }

    private JsonNode sorted(JsonNode node) {
        if (node.isObject()) {
            ObjectNode out = json.createObjectNode();
            TreeSet<String> keys = new TreeSet<>();
            node.fieldNames().forEachRemaining(keys::add);
            keys.forEach(k -> out.set(k, sorted(node.get(k))));
            return out;
        }
        if (node.isArray()) {
            ArrayNode out = json.createArrayNode();
            node.forEach(n -> out.add(sorted(n)));
            return out;
        }
        return node;
    }

    public JsonNode openapi(Flow f) {
        return OpenApi.document(json, f);
    }
}
