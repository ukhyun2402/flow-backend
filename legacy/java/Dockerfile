FROM node:22-bookworm-slim AS ui
WORKDIR /work/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build
FROM maven:3.9.11-eclipse-temurin-21 AS java
WORKDIR /work
COPY pom.xml ./
COPY src src
COPY --from=ui /work/src/main/resources/static src/main/resources/static
RUN mvn -B package -DskipTests
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=java /work/target/flow-platform-0.1.0.jar app.jar
RUN mkdir /app/data && chown 10001:10001 /app/data
USER 10001
ENV SERVER_ADDRESS=0.0.0.0
EXPOSE 8080
ENTRYPOINT ["java","-jar","app.jar"]
