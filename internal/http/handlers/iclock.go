package handlers

import (
	"errors"
	"io"
	"net/http"

	sharedratelimit "github.com/Bengo-Hub/shared-ratelimit"
	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// maxDeviceBody caps one device upload (a full ATTLOG re-sync of a busy terminal fits well).
const maxDeviceBody = 16 << 20

// ICLockHandler serves the ZKTeco PUSH (ADMS) endpoints biometric terminals call. They carry
// no JWT: the serial number must belong to a registered, active device, which also decides
// the tenant. Every reply is text/plain as the protocol expects.
type ICLockHandler struct {
	log *zap.Logger
	svc *attendance.Service
}

// NewICLockHandler builds the device endpoint handler.
func NewICLockHandler(log *zap.Logger, svc *attendance.Service) *ICLockHandler {
	return &ICLockHandler{log: log.Named("iclock"), svc: svc}
}

// RegisterRoutes mounts /iclock/* on r (called for both the root and /api/v1).
func (h *ICLockHandler) RegisterRoutes(r chi.Router) {
	r.Route("/iclock", func(ir chi.Router) {
		ir.Get("/cdata", h.CData)
		ir.Post("/cdata", h.CData)
		ir.Get("/getrequest", h.GetRequest)
		ir.Post("/devicecmd", h.DeviceCmd)
	})
}

// DeviceKey is the rate-limit key for device traffic: serial plus the trusted client IP, so
// one misbehaving terminal cannot exhaust the budget of the others behind the same NAT.
func DeviceKey(r *http.Request) string {
	return "adms:" + r.URL.Query().Get("SN") + ":" + sharedratelimit.ClientIP(r)
}

// DeviceIPKey is the per-address ceiling for device traffic, whatever serial is claimed.
func DeviceIPKey(r *http.Request) string {
	return "adms-ip:" + sharedratelimit.ClientIP(r)
}

func plain(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}

// device resolves the calling terminal or answers 401 and logs the unknown serial.
func (h *ICLockHandler) device(w http.ResponseWriter, r *http.Request) (*ent.AttendanceDevice, bool) {
	sn := r.URL.Query().Get("SN")
	dev, err := h.svc.DeviceBySerial(r.Context(), sn)
	if errors.Is(err, attendance.ErrUnknownDevice) {
		h.log.Warn("rejected unknown or inactive device", zap.String("sn", sn),
			zap.String("ip", sharedratelimit.ClientIP(r)), zap.String("path", r.URL.Path))
		plain(w, http.StatusUnauthorized, "UNKNOWN DEVICE")
		return nil, false
	}
	if err != nil {
		h.log.Error("device lookup failed", zap.String("sn", sn), zap.Error(err))
		plain(w, http.StatusInternalServerError, "ERROR")
		return nil, false
	}
	if ip := sharedratelimit.ClientIP(r); !attendance.DeviceAllowsIP(dev, ip) {
		h.log.Warn("rejected device from an address outside its allow list", zap.String("sn", sn),
			zap.String("ip", ip), zap.String("path", r.URL.Path))
		plain(w, http.StatusUnauthorized, "UNKNOWN DEVICE")
		return nil, false
	}
	return dev, true
}

// CData handles the handshake (GET) and data uploads (POST ?table=ATTLOG|OPERLOG|rtlog|options).
func (h *ICLockHandler) CData(w http.ResponseWriter, r *http.Request) {
	dev, ok := h.device(w, r)
	if !ok {
		return
	}
	q := r.URL.Query()
	h.svc.DeviceSeen(r.Context(), dev, sharedratelimit.ClientIP(r), q.Get("pushver"), "")
	if r.Method == http.MethodGet {
		plain(w, http.StatusOK, h.svc.DeviceHandshake(r.Context(), dev))
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxDeviceBody))
	if err != nil {
		plain(w, http.StatusBadRequest, "ERROR")
		return
	}
	res, err := h.svc.DeviceUpload(r.Context(), dev, q.Get("table"), q.Get("Stamp"), string(body))
	if err != nil {
		// Not OK, so the device keeps the batch and sends it again later.
		h.log.Error("device upload failed", zap.String("sn", dev.SerialNumber), zap.String("table", q.Get("table")), zap.Error(err))
		plain(w, http.StatusInternalServerError, "ERROR")
		return
	}
	if res.Received > 0 || res.Skipped > 0 {
		h.log.Info("device upload", zap.String("sn", dev.SerialNumber), zap.String("table", res.Table),
			zap.Int("received", res.Received), zap.Int64("inserted", res.Inserted),
			zap.Int64("duplicates", res.Duplicates), zap.Int("unmatched", res.Unmatched), zap.Int("skipped", res.Skipped))
	}
	plain(w, http.StatusOK, "OK")
}

// GetRequest returns queued commands ("C:<id>:<command>" lines) or "OK".
func (h *ICLockHandler) GetRequest(w http.ResponseWriter, r *http.Request) {
	dev, ok := h.device(w, r)
	if !ok {
		return
	}
	h.svc.DeviceSeen(r.Context(), dev, sharedratelimit.ClientIP(r), "", r.URL.Query().Get("INFO"))
	body, err := h.svc.DevicePoll(r.Context(), dev)
	if err != nil {
		h.log.Error("device poll failed", zap.String("sn", dev.SerialNumber), zap.Error(err))
	}
	plain(w, http.StatusOK, body)
}

// DeviceCmd records the device's command results.
func (h *ICLockHandler) DeviceCmd(w http.ResponseWriter, r *http.Request) {
	dev, ok := h.device(w, r)
	if !ok {
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		plain(w, http.StatusBadRequest, "ERROR")
		return
	}
	if _, err := h.svc.DeviceCommandReply(r.Context(), dev, string(body)); err != nil {
		h.log.Error("device command reply failed", zap.String("sn", dev.SerialNumber), zap.Error(err))
	}
	plain(w, http.StatusOK, "OK")
}
