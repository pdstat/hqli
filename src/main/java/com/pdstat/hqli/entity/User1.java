package com.pdstat.hqli.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "USERS")
public class User1 {

    @Id
    @Column(name = "USER_ID", nullable = false, updatable = false)
    private String userId;

    @Column(name = "ALT_USER_ID")
    private String altUserId;

    @Column(name = "DOB")
    private String dob;

    @Column(name = "PASSWORD")
    private String password;

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

    public String getDob() {
        return dob;
    }

    public void setDob(String dob) {
        this.dob = dob;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }
}

