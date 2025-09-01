# Multi-stage build: build the Spring Boot fat jar then run it

# ---- Build stage ----
FROM eclipse-temurin:17-jdk AS build
WORKDIR /workspace

# Copy entire project (simpler, robust if .mvn is absent)
COPY . .

# Build
RUN ./mvnw -q -DskipTests package

# ---- Run stage ----
FROM eclipse-temurin:17-jre
ENV JAVA_OPTS=""
WORKDIR /app

# Copy fat jar from build stage
COPY --from=build /workspace/target/*-SNAPSHOT.jar /app/app.jar

EXPOSE 8443
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
