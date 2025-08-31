package com.pdstat.hqli.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;

@Entity
@Table(name = "USERS")
public class User1 {

    @Id
    @Column(name = "USER_ID", nullable = false, updatable = false)
    private String userId;

    @Column(name = "ALT_USER_ID")
    private String altUserId;

    // Add one-to-one back-reference to Agent; Agent owns the relation via USER_ID FK
    @OneToOne(mappedBy = "user", fetch = FetchType.LAZY)
    private Agent agent;

    public String getUserId() {
        return userId;
    }

    public void setUserId(String userId) {
        this.userId = userId;
    }

    public String getAltUserId() {
        return altUserId;
    }

    public void setAltUserId(String altUserId) {
        this.altUserId = altUserId;
    }

    public Agent getAgent() {
        return agent;
    }

    public void setAgent(Agent agent) {
        this.agent = agent;
    }

}
