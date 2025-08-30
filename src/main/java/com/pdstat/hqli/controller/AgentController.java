package com.pdstat.hqli.controller;

import com.pdstat.hqli.model.Agent;
import com.pdstat.hqli.model.CheckAgentResponse;
import com.pdstat.hqli.repository.AgentRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AgentController {

    private final AgentRepository repository;

    public AgentController(AgentRepository repository) {
        this.repository = repository;
    }

    @PostMapping(path = "create", consumes = "application/json")
    public void createUser(@RequestBody Agent agent) {
        repository.insert(agent);
    }

    @GetMapping(path = "checkvalidagent", produces = "application/json")
    public ResponseEntity<CheckAgentResponse> checkAgent(String agentCode) {
        return ResponseEntity.ok(repository.checkValidAgent(agentCode));
    }
}
