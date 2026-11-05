package main

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/support"
	"north55/backend/internal/telemetry"
	"north55/backend/internal/training"
)

func run() error {
	cfg, err := platform.LoadConfig()
	if err != nil {
		return err
	}
	cfg.ErrorTracker, err = platform.NewErrorTracker(cfg.SentryDSN, cfg.Environment)
	if err != nil {
		return err
	}
	if cfg.ErrorTracker != nil {
		defer func() {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			cfg.ErrorTracker.Flush(ctx)
			cfg.ErrorTracker.Close()
		}()
	}
	logger, err := platform.NewApplicationLogger(os.Stdout, cfg.LogLevel, cfg.Environment == "local", cfg.ErrorTracker)
	if err != nil {
		return err
	}
	slog.SetDefault(logger)
	if cfg.ErrorTracker != nil {
		slog.Info("Sentry enabled for environment " + cfg.Environment)
	}
	cfg.Metrics = telemetry.New(cfg.EnableMetrics)
	cfg.Storage.Metrics = cfg.Metrics
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	dbConfig, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		return err
	}
	dbConfig.ConnConfig.Tracer = cfg.ErrorTracker.QueryTracer()
	db, err := pgxpool.NewWithConfig(ctx, dbConfig)
	if err != nil {
		return err
	}
	defer db.Close()
	if err = db.Ping(ctx); err != nil {
		return err
	}
	redisOptions, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		return err
	}
	redisOptions.DialTimeout = 5 * time.Second
	redisClient := redis.NewClient(redisOptions)
	defer redisClient.Close()
	var limiter platform.RateLimiter
	if cfg.EnableRateLimit {
		limitOptions := *redisOptions
		limitOptions.DialTimeout, limitOptions.ReadTimeout, limitOptions.WriteTimeout = 2*time.Second, 2*time.Second, 2*time.Second
		limitOptions.MaxRetries = -1
		limitClient := redis.NewClient(&limitOptions)
		defer limitClient.Close()
		limiter = platform.NewRedisRateLimiter(limitClient, cfg.RateLimitPerMinute, cfg.RateLimitPerSecond)
	}
	authService := &auth.Service{DB: db, Config: cfg}
	if err = authService.Bootstrap(ctx); err != nil {
		return err
	}
	mux := platform.NewRouter()
	health := &platform.Health{DB: db, Redis: redisClient, Config: cfg, Started: time.Now()}
	health.Register(mux)
	authService.Register(mux)
	(&training.Service{Auth: authService}).Register(mux)
	(&support.Service{Auth: authService}).Register(mux)
	platform.RegisterMetrics(mux, cfg)
	if err := platform.RegisterAPIDocumentation(mux, cfg); err != nil {
		return err
	}
	server := &http.Server{Addr: net.JoinHostPort(cfg.Host, cfg.Port), Handler: platform.Middleware(cfg, mux, limiter), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	done := make(chan error, 1)
	go func() {
		slog.Info("HTTP server listening", "address", server.Addr, "environment", cfg.Environment)
		done <- server.ListenAndServe()
	}()
	select {
	case err := <-done:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		return server.Shutdown(shutdown)
	}
}
func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	if err := run(); err != nil {
		slog.Error("server stopped", "exception", err)
		os.Exit(1)
	}
}
