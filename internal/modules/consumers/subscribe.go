package consumers

import (
	"context"
	"math/rand/v2"
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

// Redelivery of a failed event: at most maxDeliver attempts, each after a growing delay with
// jitter, capped.
const (
	maxDeliver = 5
	retryBase  = 5 * time.Second
	retryCap   = 5 * time.Minute
)

// retryAfter says what to do after a delivery failed: give up once the last attempt failed, else
// wait base*2^(attempt-1) (capped), less up to a quarter of it at random.
func retryAfter(delivered uint64, jitter func(time.Duration) time.Duration) (giveUp bool, delay time.Duration) {
	if delivered >= maxDeliver {
		return true, 0
	}
	if delivered < 1 {
		delivered = 1
	}
	delay = retryCap
	if delivered < 16 {
		if d := retryBase << (delivered - 1); d < retryCap {
			delay = d
		}
	}
	return false, delay - jitter(delay/4)
}

func randomJitter(max time.Duration) time.Duration {
	if max <= 0 {
		return 0
	}
	return time.Duration(rand.Int64N(int64(max)))
}

// subscribeAll registers a durable queue subscription per spec on the stream. Each message is
// decoded, skipped when the idempotency store already holds it for this consumer, handled, and
// then marked processed and acked. A handler error naks it with a growing delay (retryAfter); when
// the last attempt fails the event is terminated and logged as given up, with the reason. An
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
				delivered := uint64(maxDeliver)
				if meta, merr := msg.Metadata(); merr == nil {
					delivered = meta.NumDelivered
				}
				giveUp, delay := retryAfter(delivered, randomJitter)
				if giveUp {
					log.Error("event given up after the last attempt", zap.String("subject", s.subject),
						zap.String("event_id", evt.ID.String()), zap.Uint64("attempts", delivered), zap.Error(err))
					_ = msg.Term()
					return
				}
				log.Warn("handler failed, retrying later", zap.String("subject", s.subject),
					zap.Uint64("attempt", delivered), zap.Duration("retry_in", delay), zap.Error(err))
				_ = msg.NakWithDelay(delay)
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
			nats.MaxDeliver(maxDeliver),
			nats.DeliverAll(),
		)
		log.Info("subscription active", zap.String("subject", s.subject), zap.String("durable", s.durable))
	}
}
