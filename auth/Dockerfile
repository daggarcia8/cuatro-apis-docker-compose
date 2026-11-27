FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
COPY src ./src
RUN mvn -B package dependency:copy-dependencies -DincludeScope=runtime

FROM eclipse-temurin:21-jre
WORKDIR /app
RUN mkdir -p /data
COPY --from=build /src/target/classes ./classes
COPY --from=build /src/target/dependency ./lib
ENV DB_PATH=/data/auth.db
EXPOSE 8001
CMD ["java", "-cp", "classes:lib/*", "AuthServer"]
