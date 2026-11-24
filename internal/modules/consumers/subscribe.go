package consumers

import (
	"context"
	"time"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"go.uber.org/zap"
)

// subSpec is one durable subscription: the subject, its durable consumer name (also the
// idempotency consumer key) and the handler.
type subSpec struct {
	subject string
	durable string
	handler func(context.Context, *sharedevents.Event) error
}

// ensureStream creates a service's stream ("<name>" over "<name>.>") when its owner has not
// started yet, with the same settings the owner uses, so a startup race cannot drop events.
func ensureStream(log *zap.Logger, js nats.JetStreamContext, name string) {
	if _, err := js.StreamInfo(name); err == nil {
		return
	}
	if _, err := js.AddStream(&nats.StreamConfig{
		Name:      name,
		Subjects:  []string{name + ".>"},
		Retention: nats.LimitsPolicy,
		MaxAge:    72 * time.Hour,
		Storage:   nats.FileStorage,
	}); err != nil && err != nats.ErrStreamNameAlreadyInUse {
		log.Warn("ensure stream failed", zap.String("stream", name), zap.Error(err))
	}
}

// subscribeAll registers a durable queue subscription per spec on the stream. Each message is
// decoded, skipped when the idempotency store already holds it for this consumer, handled, and
// then marked processed and acked. A handler error naks it for redelivery (at most 5 times); an
// undecodable message is acked and dropped so it is not redelivered forever.
func subscribeAll(ctx context.Context, log *zap.Logger, js nats.JetStreamContext, stream string, idem *sharedevents.IdempotencyStore, specs []subSpec) {
	for _, s := range specs {
		s := s
		consumerName := s.durable
		sharedevents.SubscribeQueueWithRebind(log, js, stream, s.subject, s.durable, func(msg *nats.Msg) {
			evt, err := sharedevents.FromJSON(msg.Data)
			if err != nil {
				log.Error("bad event", zap.String("subject", s.subject), zap.Error(err))
				_ = msg.Ack()
				return
			}
			if idem != nil && evt.ID != uuid.Nil {
				if done, _ := idem.AlreadyProcessed(ctx, evt.ID, consumerName); done {
					_ = msg.Ack()
					return
				}
			}
			if err := s.handler(ctx, evt); err != nil {
				log.Error("handler failed", zap.String("subject", s.subject), zap.Error(err))
				_ = msg.Nak()
				return
			}
			if idem != nil && evt.ID != uuid.Nil {
				_ = idem.MarkProcessed(ctx, evt.ID, consumerName)
			}
			_ = msg.Ack()
		},
			nats.Durable(s.durable),
			nats.AckExplicit(),
			nats.AckWait(30*time.Second),
			nats.MaxDeliver(5),
			nats.DeliverAll(),
		)
		log.Info("subscription active", zap.String("subject", s.subject), zap.String("durable", s.durable))
	}
}
