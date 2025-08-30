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
     * Creates a new User1 via the factory and inserts it.
     * @return the managed entity instance.
     */
    @Transactional
    public void insert(Agent agent) {
        User1 agentEntity = new User1();
        agentEntity.setDob(agent.getDob());
        agentEntity.setAltUserId(agent.altUserId);
        agentEntity.setUserId(agent.getUserId());
        agentEntity.setPassword(agent.getPassword());
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
