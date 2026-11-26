package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand/v2"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// How long a member list is used without asking auth-api again, and how long an old one may stand
// in while auth-api cannot be reached.
const (
	memberFresh = 30 * time.Second
	memberStale = 10 * time.Minute
)

// MemberDirectory answers who is an active member of a tenant, from auth-api's member list (GET
// /api/v1/s2s/{tenant}/users, active members only).
type MemberDirectory struct {
	base, key string
	http      *http.Client
	now       func() time.Time
	jitter    func(time.Duration) time.Duration

	mu    sync.Mutex
	lists map[string]*memberList
}

type memberList struct {
	mu  sync.Mutex
	ids map[string]bool
	at  time.Time
	// After a failed fetch nobody asks auth-api again before retryAt; the wait doubles with each
	// failure in a row (with jitter, capped), so an outage never turns into a flood of calls.
	failures int
	retryAt  time.Time
	lastErr  error
}

// Waits after a failed member fetch: memberRetryBase doubling per failure, at most memberRetryCap.
const (
	memberRetryBase = time.Second
	memberRetryCap  = time.Minute
)

// memberRetryIn is the wait after the given number of failures in a row, less up to a quarter at
// random.
func memberRetryIn(failures int, jitter func(time.Duration) time.Duration) time.Duration {
	d := memberRetryCap
	if failures >= 1 && failures <= 7 {
		if step := memberRetryBase << (failures - 1); step < d {
			d = step
		}
	}
	return d - jitter(d/4)
}

func randomJitter(max time.Duration) time.Duration {
	if max <= 0 {
		return 0
	}
	return time.Duration(rand.Int64N(int64(max)))
}

// NewMemberDirectory is nil when the service key or URL is missing (local development).
func NewMemberDirectory(authURL, apiKey string) *MemberDirectory {
	authURL, apiKey = strings.TrimRight(strings.TrimSpace(authURL), "/"), strings.TrimSpace(apiKey)
	if authURL == "" || apiKey == "" {
		return nil
	}
	return &MemberDirectory{base: authURL, key: apiKey, http: &http.Client{Timeout: 5 * time.Second},
		now: time.Now, jitter: randomJitter, lists: map[string]*memberList{}}
}

// ActiveMember reports whether a user (auth user id) is an active member of the tenant.
func (d *MemberDirectory) ActiveMember(ctx context.Context, tenantID, userID string) (bool, error) {
	d.mu.Lock()
	l := d.lists[tenantID]
	if l == nil {
		l = &memberList{}
		d.lists[tenantID] = l
	}
	d.mu.Unlock()

	l.mu.Lock()
	defer l.mu.Unlock()
	now := d.now()
	if (l.ids == nil || now.Sub(l.at) > memberFresh) && !now.Before(l.retryAt) {
		ids, err := d.fetch(ctx, tenantID)
		if err == nil {
			l.ids, l.at, l.failures, l.retryAt, l.lastErr = ids, now, 0, time.Time{}, nil
		} else {
			l.failures++
			l.retryAt, l.lastErr = now.Add(memberRetryIn(l.failures, d.jitter)), err
		}
	}
	if l.ids == nil || now.Sub(l.at) > memberStale {
		if l.lastErr != nil {
			return false, l.lastErr
		}
		return false, fmt.Errorf("auth members: no current member list")
	}
	return l.ids[strings.ToLower(userID)], nil
}

func (d *MemberDirectory) fetch(ctx context.Context, tenantID string) (map[string]bool, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, d.base+"/api/v1/s2s/"+url.PathEscape(tenantID)+"/users", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-API-Key", d.key)
	resp, err := d.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("auth members: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("auth members: HTTP %d", resp.StatusCode)
	}
	// auth-api answers with a JSON array of members; null or any other shape is not an empty company.
	var users *[]struct {
		ID string `json:"id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&users); err != nil {
		return nil, fmt.Errorf("auth members: %w", err)
	}
	if users == nil {
		return nil, fmt.Errorf("auth members: no member list in the answer")
	}
	out := make(map[string]bool, len(*users))
	for _, u := range *users {
		out[strings.ToLower(u.ID)] = true
	}
	return out, nil
}
