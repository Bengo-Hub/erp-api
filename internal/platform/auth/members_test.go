package auth

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

type fakeAuth struct {
	srv    *httptest.Server
	answer string
	status int
	calls  atomic.Int32
}

func newFakeAuth(t *testing.T) *fakeAuth {
	f := &fakeAuth{answer: `[{"id":"AAAA-1","email":"a@x","roles":["admin"]}]`, status: http.StatusOK}
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.calls.Add(1)
		if r.URL.Path != "/api/v1/s2s/t1/users" || r.Header.Get("X-API-Key") != "k" {
			http.Error(w, "bad", http.StatusBadRequest)
			return
		}
		w.WriteHeader(f.status)
		_, _ = w.Write([]byte(f.answer))
	}))
	t.Cleanup(f.srv.Close)
	return f
}

// directory returns a directory on a clock the test moves, with no jitter.
func (f *fakeAuth) directory(now *time.Time) *MemberDirectory {
	d := NewMemberDirectory(f.srv.URL+"/", "k")
	d.now = func() time.Time { return *now }
	d.jitter = func(time.Duration) time.Duration { return 0 }
	return d
}

// TestMemberDirectoryReadsAuthList: auth-api's member list is a JSON array; ids are matched without
// case, an old list stands in briefly while auth-api is down, and a broken answer is an error.
func TestMemberDirectoryReadsAuthList(t *testing.T) {
	f := newFakeAuth(t)
	now := time.Now()
	d := f.directory(&now)
	ctx := context.Background()
	if ok, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err != nil || !ok {
		t.Fatalf("member: %v %v", ok, err)
	}
	if ok, err := d.ActiveMember(ctx, "t1", "bbbb-2"); err != nil || ok {
		t.Fatalf("not a member: %v %v", ok, err)
	}

	f.status = http.StatusBadGateway
	now = now.Add(time.Minute)
	if ok, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err != nil || !ok {
		t.Fatalf("old list should stand in: %v %v", ok, err)
	}
	now = now.Add(time.Hour)
	if _, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err == nil {
		t.Fatal("a list older than the stale limit must not be used")
	}

	f.status, f.answer = http.StatusOK, `null`
	now = now.Add(time.Hour)
	if _, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err == nil {
		t.Fatal("null is not an empty company")
	}
	f.answer = `{"users":[]}`
	now = now.Add(time.Hour)
	if _, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err == nil {
		t.Fatal("an object is not the member list")
	}
	f.answer = `[]`
	now = now.Add(time.Hour)
	if ok, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err != nil || ok {
		t.Fatalf("empty company: %v %v", ok, err)
	}
	if NewMemberDirectory("", "k") != nil || NewMemberDirectory(f.srv.URL, " ") != nil {
		t.Fatal("missing URL or key must give no directory")
	}
}

// TestMemberDirectoryBacksOff: while auth-api is down, a burst of lookups makes one call, the next
// call waits twice as long after each failure up to the cap, and a success resets the wait.
func TestMemberDirectoryBacksOff(t *testing.T) {
	f := newFakeAuth(t)
	f.status = http.StatusServiceUnavailable
	now := time.Now()
	d := f.directory(&now)
	ctx := context.Background()
	burst := func() {
		t.Helper()
		for i := 0; i < 50; i++ {
			if _, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err == nil {
				t.Fatal("no list: lookups must fail while auth-api is down")
			}
		}
	}
	burst()
	if n := f.calls.Load(); n != 1 {
		t.Fatalf("calls in the first burst: %d", n)
	}
	// Waits of 1s, 2s, 4s ...: just before each one ends nothing is called, at its end one call.
	wait := time.Second
	for i := 2; i <= 9; i++ {
		now = now.Add(wait - time.Millisecond)
		burst()
		if n := f.calls.Load(); int(n) != i-1 {
			t.Fatalf("before the wait of %v ended: %d calls", wait, n)
		}
		now = now.Add(time.Millisecond)
		burst()
		if n := f.calls.Load(); int(n) != i {
			t.Fatalf("after the wait of %v: %d calls", wait, n)
		}
		if wait *= 2; wait > memberRetryCap {
			wait = memberRetryCap
		}
	}
	if got := memberRetryIn(100, func(time.Duration) time.Duration { return 0 }); got != memberRetryCap {
		t.Fatalf("cap: %v", got)
	}
	if got := memberRetryIn(3, func(m time.Duration) time.Duration { return m }); got != 3*time.Second {
		t.Fatalf("jitter takes at most a quarter: %v", got)
	}

	f.status = http.StatusOK
	now = now.Add(memberRetryCap)
	if ok, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err != nil || !ok {
		t.Fatalf("after recovery: %v %v", ok, err)
	}
	f.status = http.StatusServiceUnavailable
	calls := f.calls.Load()
	now = now.Add(memberFresh + time.Second)
	burst2 := func() {
		for i := 0; i < 50; i++ {
			if ok, err := d.ActiveMember(ctx, "t1", "aaaa-1"); err != nil || !ok {
				t.Fatalf("the recent list stands in: %v %v", ok, err)
			}
		}
	}
	burst2()
	now = now.Add(time.Second - time.Millisecond)
	burst2()
	if n := f.calls.Load() - calls; n != 1 {
		t.Fatalf("a success resets the wait to 1s: %d calls", n)
	}
}
