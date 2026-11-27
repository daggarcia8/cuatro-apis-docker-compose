FROM golang:1.25-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go .
RUN CGO_ENABLED=0 go build -o /orders .

FROM debian:bookworm-slim
WORKDIR /app
RUN mkdir -p /data
COPY --from=build /orders /app/orders
ENV DB_PATH=/data/orders.db
EXPOSE 8002
CMD ["/app/orders"]
