package consumers

import (
	"context"
	"fmt"
	"time"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"go.uber.org/zap"
)

// projectsStream is projects-api's stream; it captures project.> (subject project.<type>).
const projectsStream = "projects"

// ProjectAllocations is what the projects consumer changes (employees.Service).
type ProjectAllocations interface {
	RenameProjectAllocations(ctx context.Context, tenantID, projectID uuid.UUID, name string) (int, error)
	EndProjectAllocations(ctx context.Context, tenantID, projectID uuid.UUID, closedOn time.Time) (int, error)
}

// ProjectSyncConsumer keeps employee project allocations in step with projects-api: a renamed
// project's name is refreshed, and a closed or deleted project's allocations end on that day.
type ProjectSyncConsumer struct {
	log  *zap.Logger
	svc  ProjectAllocations
	idem *sharedevents.IdempotencyStore
	// Entitled reports whether the tenant's plan includes erp; nil lets every tenant through.
	Entitled func(ctx context.Context, tenantID uuid.UUID) bool
}

func NewProjectSyncConsumer(log *zap.Logger, svc ProjectAllocations, idem *sharedevents.IdempotencyStore) *ProjectSyncConsumer {
	return &ProjectSyncConsumer{log: log.Named("consumers.project_sync"), svc: svc, idem: idem}
}

// Start binds to the stream that captures project events (creating projects-api's stream when it
// has not started yet) and registers the durable subscriptions.
func (c *ProjectSyncConsumer) Start(ctx context.Context, nc *nats.Conn) error {
	if nc == nil {
		c.log.Warn("NATS not available; project-sync consumers disabled")
		return nil
	}
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("project-sync: jetstream init: %w", err)
	}
	stream, err := js.StreamNameBySubject("project.updated")
	if err != nil || stream == "" {
		stream = projectsStream
		if _, aerr := js.AddStream(&nats.StreamConfig{Name: stream, Subjects: []string{"project.>"},
			Retention: nats.LimitsPolicy, MaxAge: 72 * time.Hour, Storage: nats.FileStorage}); aerr != nil && aerr != nats.ErrStreamNameAlreadyInUse {
			return fmt.Errorf("project-sync: ensure stream: %w", aerr)
		}
	}
	subscribeAll(ctx, c.log, js, stream, c.idem, []subSpec{
		{"project.updated", "erp-project-updated", c.handleUpdated},
		{"project.closed", "erp-project-closed", c.handleEnded},
		{"project.deleted", "erp-project-deleted", c.handleEnded},
	})
	return nil
}

// projectIDs reads tenant and project from the envelope, falling back to the payload.
func projectIDs(evt *sharedevents.Event) (tenantID, projectID uuid.UUID, err error) {
	tenantID = tenantIDFromEvent(evt)
	projectID = evt.AggregateID
	if projectID == uuid.Nil {
		projectID = parseUUID(str(evt.Payload, "id"))
	}
	if tenantID == uuid.Nil || projectID == uuid.Nil {
		return uuid.Nil, uuid.Nil, fmt.Errorf("project event without tenant or project id")
	}
	return tenantID, projectID, nil
}

func (c *ProjectSyncConsumer) entitled(ctx context.Context, tenantID uuid.UUID) bool {
	return c.Entitled == nil || c.Entitled(ctx, tenantID)
}

func (c *ProjectSyncConsumer) handleUpdated(ctx context.Context, evt *sharedevents.Event) error {
	tenantID, projectID, err := projectIDs(evt)
	if err != nil {
		return err
	}
	if !c.entitled(ctx, tenantID) {
		return nil
	}
	n, err := c.svc.RenameProjectAllocations(ctx, tenantID, projectID, str(evt.Payload, "name"))
	if err != nil {
		return err
	}
	if n > 0 {
		c.log.Info("project name refreshed on allocations", zap.String("project_id", projectID.String()), zap.Int("allocations", n))
	}
	return nil
}

func (c *ProjectSyncConsumer) handleEnded(ctx context.Context, evt *sharedevents.Event) error {
	tenantID, projectID, err := projectIDs(evt)
	if err != nil {
		return err
	}
	if !c.entitled(ctx, tenantID) {
		return nil
	}
	closedOn := evt.Timestamp
	if closedOn.IsZero() {
		closedOn = time.Now().UTC()
	}
	n, err := c.svc.EndProjectAllocations(ctx, tenantID, projectID, closedOn)
	if err != nil {
		return err
	}
	c.log.Info("allocations ended for a closed project", zap.String("project_id", projectID.String()),
		zap.String("event", evt.EventType), zap.Int("allocations", n))
	return nil
}
