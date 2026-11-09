FROM golang:1.27.1-bookworm@sha256:69a7b9788769bec032d238959b61854e9ae87f57be9029ec04e9885fabf99195 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ ./cmd/
COPY internal/ ./internal/
COPY deploy/healthcheck.go ./deploy/healthcheck.go
RUN CGO_ENABLED=0 go build -trimpath -o /out/api ./cmd/api && \
    CGO_ENABLED=0 go build -trimpath -o /out/migrate-submission-state ./cmd/migrate-submission-state && \
    CGO_ENABLED=0 go build -trimpath -o /out/healthcheck ./deploy/healthcheck.go && \
    mkdir -p /data/media /data/feedback /data/backups

FROM gcr.io/distroless/static-debian13:nonroot@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3
COPY --from=build /out/api /usr/local/bin/55north-api
COPY --from=build /out/migrate-submission-state /usr/local/bin/migrate-submission-state
COPY --from=build /out/healthcheck /usr/local/bin/55north-healthcheck
COPY --from=build --chown=65532:65532 /data/ /var/lib/55north/
COPY --from=build /src/internal/reportpdf/fonts/LICENSE /licenses/DejaVu-fonts.txt
USER 65532:65532
WORKDIR /var/lib/55north
ENV HOST=0.0.0.0 PORT=8000 API_PREFIX=/api ENVIRONMENT=prod \
    MEDIA_UPLOAD_DIR=/var/lib/55north/media FEEDBACK_UPLOAD_DIR=/var/lib/55north/feedback \
    BACKUP_DIR=/var/lib/55north/backups
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=13s --start-period=30s --retries=3 CMD ["/usr/local/bin/55north-healthcheck", "ready"]
ENTRYPOINT ["/usr/local/bin/55north-api"]
