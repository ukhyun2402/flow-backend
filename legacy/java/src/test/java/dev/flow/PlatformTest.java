package dev.flow;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import dev.flow.platform.Repository;
import java.nio.file.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = { "flow.data=target/test-platform-data" })
@AutoConfigureMockMvc
class PlatformTest {

    @Autowired
    MockMvc mvc;

    @Autowired
    Repository repository;

    @Test
    void platformRequiresToken() throws Exception {
        mvc.perform(get("/api/flows")).andExpect(status().isUnauthorized());
    }

    @Test
    void runtimeRoutesAreAbsentInPlatform() throws Exception {
        mvc.perform(
            post("/hello").contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"test\"}")
        ).andExpect(status().isNotFound());
    }

    @Test
    void revisionsAreImmutableAndPathsCannotEscape() throws Exception {
        var json = new com.fasterxml.jackson.databind.ObjectMapper();
        var flow = json.readValue(
            Files.readString(Path.of("examples/hello-flow.json")),
            dev.flow.core.Flow.class
        );
        var temp = Files.createTempDirectory(Path.of("target"), "repository-");
        var repo = new Repository(temp.toString(), json);
        repo.save(flow);
        assertThrows(dev.flow.core.FlowFault.class, () -> repo.save(flow));
        assertEquals(flow, repo.get(flow.id(), 1));
        assertThrows(dev.flow.core.FlowFault.class, () -> repo.get("../outside", 1));
    }
}
