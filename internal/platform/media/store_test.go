package media

import (
	"bytes"
	"context"
	"image"
	"image/png"
	"strings"
	"testing"

	"github.com/Bengo-Hub/httpware/objectstore"
	"github.com/google/uuid"
)

func localStore(t *testing.T) *Store {
	t.Helper()
	RegisterMediaTypes()
	s, err := objectstore.New("erp", objectstore.Config{LocalRoot: t.TempDir(), LocalURLBase: "http://localhost:4000"})
	if err != nil {
		t.Fatal(err)
	}
	return NewStore(s)
}

func TestSaveGetRelease(t *testing.T) {
	ctx := context.Background()
	m := localStore(t)
	tenant, cand := uuid.New(), uuid.New()

	if _, err := m.SaveResume(ctx, tenant, cand, "cv.exe", strings.NewReader("x")); err == nil {
		t.Fatal("an unsupported extension must be refused")
	}
	if _, err := m.SaveResume(ctx, tenant, cand, "cv.pdf", strings.NewReader("")); err == nil {
		t.Fatal("an empty file must be refused")
	}
	key, err := m.SaveResume(ctx, tenant, cand, "CV.PDF", strings.NewReader("%PDF-1.4 resume"))
	if err != nil {
		t.Fatal(err)
	}
	if want := "erp/" + tenant.String() + "/resumes/" + cand.String() + "/"; !strings.HasPrefix(key, want) || !strings.HasSuffix(key, ".pdf") {
		t.Fatalf("key %q", key)
	}
	body, ct, err := m.Get(ctx, key)
	if err != nil || string(body) != "%PDF-1.4 resume" || ct != "application/pdf" {
		t.Fatalf("get: %q %q %v", body, ct, err)
	}
	if _, _, err := m.Get(ctx, "other/"+tenant.String()+"/resumes/x.pdf"); err == nil {
		t.Fatal("a key of another service must not be read")
	}

	// A receipt named .jpg must really be a JPEG; a PNG passes as .png and is re-encoded.
	var buf bytes.Buffer
	_ = png.Encode(&buf, image.NewRGBA(image.Rect(0, 0, 4, 4)))
	claim := uuid.New()
	if _, err := m.SaveClaimAttachment(ctx, tenant, claim, "receipt.jpg", bytes.NewReader(buf.Bytes())); err == nil {
		t.Fatal("a PNG named .jpg must be refused")
	}
	receipt, err := m.SaveClaimAttachment(ctx, tenant, claim, "receipt.png", bytes.NewReader(buf.Bytes()))
	if err != nil {
		t.Fatal(err)
	}

	// Release deletes only a replaced key of this service.
	if err := m.Release(ctx, receipt, receipt); err != nil {
		t.Fatal(err)
	}
	if _, _, err := m.Get(ctx, receipt); err != nil {
		t.Fatal("releasing the current key must keep it")
	}
	if err := m.Release(ctx, "https://elsewhere.example/cv.pdf", key); err != nil {
		t.Fatal(err)
	}
	if err := m.Release(ctx, receipt, key); err != nil {
		t.Fatal(err)
	}
	if _, _, err := m.Get(ctx, receipt); err == nil {
		t.Fatal("a released file must be gone")
	}
	if u := m.URL("https://elsewhere.example/cv.pdf"); u != "https://elsewhere.example/cv.pdf" {
		t.Fatalf("external links pass through: %q", u)
	}
}
