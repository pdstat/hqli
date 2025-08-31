package com.pdstat.hqli.repository;

import com.pdstat.hqli.entity.User1;
import com.pdstat.hqli.model.*;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class AgentRepository {

    private static final String CHECK_AGENT_EXISTS = "select count(*) from com.pdstat.hqli.entity.User1 usr " +
            "where usr.userId = '%s' or usr.altUserId = '%s'";

    @PersistenceContext
    private EntityManager em;

    /**
     * Creates a new User1 and Agent (entity) and inserts them into USERS and AGENTS tables.
     */
    @Transactional
    public void insert(Agent agentDto) {
        // Persist base user first
        User1 user = new User1();
        user.setUserId(agentDto.getUserId());
        user.setAltUserId(agentDto.getAltUserId());
        em.persist(user);

        // Persist agent details linked one-to-one to the user
        com.pdstat.hqli.entity.Agent agentEntity = new com.pdstat.hqli.entity.Agent();
        // Use the provided userId as agentId if no separate agent id exists in the DTO
        agentEntity.setAgentId(agentDto.getUserId());
        agentEntity.setUser(user);
        agentEntity.setDob(agentDto.getDob());
        agentEntity.setPassword(agentDto.getPassword());
        agentEntity.setEmail(agentDto.getEmail());
        agentEntity.setFirstName(agentDto.getFirstName());
        agentEntity.setLastName(agentDto.getLastName());
        em.persist(agentEntity);
    }

    public CheckAgentResponse checkValidAgent(String agentCode) {
        CheckAgentResponse resp = new CheckAgentResponse();
        try {
            String hql = String.format(CHECK_AGENT_EXISTS, agentCode, agentCode);

            Long count = em.createQuery(hql, Long.class).getSingleResult();

            if (count != null && count > 0L) {
                // User exists
                StatusMessage sm = new StatusMessage();
                sm.setStatusMsg("Agent Already Registered");
                sm.setPageName("NewUser");

                Payload payload = new Payload();
                payload.setStatusMsg(sm);

                MessageInfo mi = new MessageInfo();
                mi.setMessage("Failed to register user");
                mi.setMsgStatus("failure");
                mi.setStatusCode("400");

                resp.setPayload(payload);
                resp.setMsgInfo(mi);
            } else {
                // User does not exist
                Payload payload = new Payload(); // empty -> {}
                MessageInfo mi = new MessageInfo();
                mi.setMessage(null);
                mi.setMsgStatus("failure");
                mi.setStatusCode("401");

                resp.setPayload(payload);
                resp.setMsgInfo(mi);
            }
        } catch (Exception e) {
            Payload payload = new Payload(); // empty -> {}

            MessageInfo mi = new MessageInfo();
            mi.setMessage(e.toString());
            mi.setMsgStatus("failure");
            mi.setStatusCode("401");

            resp.setPayload(payload);
            resp.setMsgInfo(mi);
        }
        return resp;
    }

}
