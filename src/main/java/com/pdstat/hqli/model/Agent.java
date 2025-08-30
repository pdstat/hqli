package com.pdstat.hqli.model;

public class Agent {

    public String userId;

    public String altUserId;

    public String dob;

    public String password;

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
