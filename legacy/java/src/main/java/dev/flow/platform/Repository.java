package dev.flow.platform;

import com.fasterxml.jackson.databind.*;
import dev.flow.core.*;
import java.nio.file.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "flow.mode", havingValue = "platform", matchIfMissing = true)
public class Repository {

    private final Path root;
    private final ObjectMapper json;

    public Repository(@Value("${flow.data:data}") String root, ObjectMapper json) throws Exception {
        this.root = Path.of(root).toAbsolutePath();
        this.json = json;
        Files.createDirectories(this.root.resolve("flows"));
    }

    private Path directory(String id) {
        if (!id.matches("[a-zA-Z0-9_-]{1,80}")) throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "Invalid ID"
        );
        return root.resolve("flows").resolve(id);
    }

    public synchronized void save(Flow flow) throws Exception {
        Path dir = directory(flow.id());
        Files.createDirectories(dir);
        Path file = dir.resolve(flow.revision() + ".json");
        if (Files.exists(file)) throw new FlowFault(
            "REVISION_CONFLICT",
            409,
            "Revision already exists"
        );
        Path temp = Files.createTempFile(dir, "revision-", ".tmp");
        try {
            Files.writeString(temp, json.writerWithDefaultPrettyPrinter().writeValueAsString(flow));
            Files.move(temp, file, StandardCopyOption.ATOMIC_MOVE);
        } finally {
            Files.deleteIfExists(temp);
        }
        audit("FLOW_SAVED", flow.id(), flow.revision());
    }

    public Flow get(String id, int revision) throws Exception {
        Path file = directory(id).resolve(revision + ".json");
        if (!Files.isRegularFile(file)) throw new FlowFault(
            "NOT_FOUND",
            404,
            "Flow revision not found"
        );
        return json.readValue(Files.readString(file), Flow.class);
    }

    public List<JsonNode> list() throws Exception {
        List<JsonNode> list = new ArrayList<>();
        try (var dirs = Files.list(root.resolve("flows"))) {
            for (Path dir : dirs.filter(Files::isDirectory).sorted().toList())
                try (var files = Files.list(dir)) {
                    for (Path file : files
                        .filter(p -> p.toString().endsWith(".json"))
                        .sorted()
                        .toList()) {
                        Flow f = json.readValue(Files.readString(file), Flow.class);
                        list.add(
                            json
                                .createObjectNode()
                                .put("id", f.id())
                                .put("name", f.name())
                                .put("revision", f.revision())
                        );
                    }
                }
        }
        return list;
    }

    public synchronized void audit(String event, String id, int revision) throws Exception {
        append(
            "audit.jsonl",
            Map.of(
                "event",
                event,
                "flowId",
                id,
                "revision",
                revision,
                "at",
                java.time.Instant.now().toString()
            )
        );
    }

    public synchronized void trace(List<Engine.Trace> trace) throws Exception {
        for (Engine.Trace t : trace) append("traces.jsonl", t);
    }

    private void append(String file, Object value) throws Exception {
        Path p = root.resolve(file);
        if (Files.exists(p) && Files.size(p) > 10_000_000) Files.move(
            p,
            root.resolve(file + ".previous"),
            StandardCopyOption.REPLACE_EXISTING
        );
        Files.writeString(
            p,
            json.writeValueAsString(value) + "\n",
            StandardOpenOption.CREATE,
            StandardOpenOption.APPEND
        );
    }

    public synchronized List<JsonNode> history(String file) throws Exception {
        Path p = root.resolve(file);
        List<JsonNode> out = new ArrayList<>();
        if (Files.exists(p)) try (var lines = Files.lines(p)) {
            for (String line : lines.toList()) {
                if (out.size() >= 500) out.remove(0);
                out.add(json.readTree(line));
            }
        }
        return out;
    }
}
