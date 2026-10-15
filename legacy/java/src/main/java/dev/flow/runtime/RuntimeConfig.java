package dev.flow.runtime;

import com.fasterxml.jackson.databind.*;
import dev.flow.core.*;
import dev.flow.db.Databases;
import java.nio.file.*;
import org.springframework.context.annotation.*;

@Configuration
public class RuntimeConfig {

    @Bean
    public Validator validator() {
        return new Validator();
    }

    @Bean(destroyMethod = "close")
    public Databases databases(ObjectMapper json) throws Exception {
        String path = System.getenv("FLOW_DATABASE_CONFIG");
        return new Databases(
            json,
            path == null ? json.createObjectNode() : json.readTree(Files.readString(Path.of(path)))
        );
    }

    @Bean
    public HttpServices services(ObjectMapper json) throws Exception {
        String path = System.getenv("FLOW_SERVICE_CONFIG");
        return new HttpServices(
            json,
            path == null ? json.createObjectNode() : json.readTree(Files.readString(Path.of(path)))
        );
    }

    @Bean
    public Engine engine(ObjectMapper json, Databases databases, HttpServices services) {
        return new Engine(json, databases, services);
    }
}
