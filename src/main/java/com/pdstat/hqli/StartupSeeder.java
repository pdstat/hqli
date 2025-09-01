package com.pdstat.hqli;

import com.pdstat.hqli.model.Agent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.List;

@Component
public class StartupSeeder implements ApplicationListener<ApplicationReadyEvent> {

    private static final Logger log = LoggerFactory.getLogger(StartupSeeder.class);

    @Value("${server.port:8443}")
    private int serverPort;

    // Allow disabling via env/properties if needed
    @Value("${app.seed.enabled:true}")
    private boolean seedEnabled;

    private final RestTemplate rest = new RestTemplate();

    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        if (!seedEnabled) {
            log.info("[seed] Seeding disabled (app.seed.enabled=false)");
            return;
        }
        // Small delay to ensure the embedded server is fully bound
        try { Thread.sleep(300L); } catch (InterruptedException ignored) {}

        String baseUrl = "http://localhost:" + serverPort;
        String createUrl = baseUrl + "/create";
        log.info("[seed] Seeding 10 Agent records via {}", createUrl);

        List<Agent> toCreate = makeSeedAgents();
        int created = 0;
        for (Agent a : toCreate) {
            try {
                HttpHeaders headers = new HttpHeaders();
                headers.setContentType(MediaType.APPLICATION_JSON);
                HttpEntity<Agent> req = new HttpEntity<>(a, headers);
                ResponseEntity<Void> resp = rest.postForEntity(createUrl, req, Void.class);
                created++;
            } catch (Exception ex) {
                // Likely duplicates on re-run; swallow to keep idempotent-ish
                log.debug("[seed] create failed (likely exists): {} -> {}", a.getUserId(), ex.toString());
            }
        }
        log.info("[seed] Done. Created {} (or already existed)", created);
    }

    private List<Agent> makeSeedAgents() {
        List<Agent> list = new ArrayList<>();
        // Deterministic 10 users: 60002650..60002659
        for (int i = 0; i < 10; i++) {
            String uid = String.format("6000265%d", i);
            Agent a = new Agent();
            a.setUserId(uid);
            a.setAltUserId(String.format("ALT%03d", i));
            a.setDob(String.format("199%d-0%d-0%d", (i % 3), ((i % 8) + 1), ((i % 9) + 1)));
            a.setPassword(String.format("pass%04d", i));
            a.setFirstName("User" + i);
            a.setLastName("Test");
            a.setEmail(String.format("user%d@example.com", i));
            list.add(a);
        }
        return list;
    }
}
