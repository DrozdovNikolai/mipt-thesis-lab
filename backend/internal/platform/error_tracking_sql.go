package platform

import (
	"context"

	"github.com/getsentry/sentry-go"
	"github.com/jackc/pgx/v5"
)

type trackedQueryKey struct{}
type trackedQuery struct{ span *sentry.Span }

// QueryTracer records statements within a request transaction, following the
// source SQLAlchemy integration. Bind parameters are never attached.
func (t *ErrorTracker) QueryTracer() pgx.QueryTracer {
	if t == nil {
		return nil
	}
	return t
}

func (t *ErrorTracker) TraceQueryStart(ctx context.Context, conn *pgx.Conn, data pgx.TraceQueryStartData) context.Context {
	if t == nil || sentry.SpanFromContext(ctx) == nil {
		return ctx
	}
	t.hub(ctx).AddBreadcrumb(&sentry.Breadcrumb{Category: "query", Message: data.SQL}, nil)
	span := sentry.StartSpan(ctx, "db", sentry.WithDescription(data.SQL))
	span.SetData("db.system", "postgresql")
	if conn != nil {
		cfg := conn.Config()
		span.SetData("db.name", cfg.Database)
		span.SetData("server.address", cfg.Host)
		span.SetData("server.port", cfg.Port)
	}
	return context.WithValue(span.Context(), trackedQueryKey{}, trackedQuery{span: span})
}

func (t *ErrorTracker) TraceQueryEnd(ctx context.Context, _ *pgx.Conn, data pgx.TraceQueryEndData) {
	query, ok := ctx.Value(trackedQueryKey{}).(trackedQuery)
	if !ok {
		return
	}
	if data.Err != nil {
		query.span.Status = sentry.SpanStatusInternalError
	}
	query.span.Finish()
}
