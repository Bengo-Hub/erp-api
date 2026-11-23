package attendance

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// ZKTeco PUSH (ADMS) wire format. Devices post tab-separated text; every line is parsed
// leniently, and a line that cannot be read is skipped and counted rather than failing the
// whole batch, because the device would otherwise resend the same batch forever.

// admsTimeLayout is the device's local wall-clock format.
const admsTimeLayout = "2006-01-02 15:04:05"

// ParsedPunch is one ATTLOG line.
type ParsedPunch struct {
	PIN      string
	At       time.Time
	Status   int
	Verify   int
	WorkCode string
	Raw      string
}

// ParseATTLOG reads ATTLOG lines: PIN, DateTime, Status, Verify, WorkCode, reserved fields.
// Times are device wall-clock time in loc.
func ParseATTLOG(body string, loc *time.Location) (out []ParsedPunch, skipped int) {
	for _, line := range splitLines(body) {
		f := strings.Split(line, "\t")
		if len(f) < 2 {
			skipped++
			continue
		}
		pin := strings.TrimSpace(f[0])
		at, err := time.ParseInLocation(admsTimeLayout, strings.TrimSpace(f[1]), loc)
		if pin == "" || err != nil {
			skipped++
			continue
		}
		p := ParsedPunch{PIN: pin, At: at, Raw: line}
		if len(f) > 2 {
			p.Status = atoiOr(f[2], 0)
		}
		if len(f) > 3 {
			p.Verify = atoiOr(f[3], 0)
		}
		if len(f) > 4 {
			p.WorkCode = strings.TrimSpace(f[4])
		}
		out = append(out, p)
	}
	return out, skipped
}

// OperLog is what the server keeps from an OPERLOG upload.
type OperLog struct {
	Users []DeviceUser // USER lines (enrolled or changed users)
	Ops   int          // OPLOG lines
	Other int          // FP, FACE, BIODATA and other lines
}

// DeviceUser is a USER line: PIN=1\tName=Jane\tPri=0\tPasswd=\tCard=\tGrp=1.
type DeviceUser struct {
	PIN  string
	Name string
	Pri  int
	Card string
}

// ParseOPERLOG reads an OPERLOG body.
func ParseOPERLOG(body string) OperLog {
	var out OperLog
	for _, line := range splitLines(body) {
		switch {
		case strings.HasPrefix(line, "USER "):
			kv := parseKV(strings.TrimPrefix(line, "USER "), "\t")
			if kv["PIN"] == "" {
				out.Other++
				continue
			}
			out.Users = append(out.Users, DeviceUser{PIN: kv["PIN"], Name: kv["Name"], Pri: atoiOr(kv["Pri"], 0), Card: kv["Card"]})
		case strings.HasPrefix(line, "OPLOG"):
			out.Ops++
		default:
			out.Other++
		}
	}
	return out
}

// ParsedAccess is one rtlog line from an access-control device.
type ParsedAccess struct {
	PIN     string
	At      time.Time
	Door    int
	Event   int
	InOut   int
	Verify  int
	CardNo  string
	Granted bool
	Raw     string
}

// grantedEvents are ZKTeco access event codes that mean the door opened for a person.
var grantedEvents = map[int]bool{0: true, 1: true, 2: true, 3: true, 4: true, 5: true, 8: true,
	14: true, 15: true, 16: true, 17: true, 18: true, 19: true, 202: true}

// accessResult classifies an event code: granted, denied (verification refused), or neither
// (door sensor, alarm and other status events, which are not stored as access events).
func accessResult(code int) (granted, isAccess bool) {
	if grantedEvents[code] {
		return true, true
	}
	if code >= 20 && code <= 48 {
		return false, true
	}
	return false, false
}

// ParseRTLog reads rtlog lines (key=value pairs separated by tabs): time, pin, cardno,
// eventaddr (door), event, inoutstatus, verifytype.
func ParseRTLog(body string, loc *time.Location) (out []ParsedAccess, skipped int) {
	for _, line := range splitLines(body) {
		kv := parseKV(line, "\t")
		at, err := time.ParseInLocation(admsTimeLayout, kv["time"], loc)
		if err != nil {
			skipped++
			continue
		}
		code := atoiOr(kv["event"], -1)
		granted, isAccess := accessResult(code)
		if !isAccess {
			skipped++
			continue
		}
		pin := kv["pin"]
		if pin == "0" {
			pin = ""
		}
		out = append(out, ParsedAccess{
			PIN: pin, At: at, Door: atoiOr(kv["eventaddr"], 1), Event: code,
			InOut: atoiOr(kv["inoutstatus"], 0), Verify: atoiOr(kv["verifytype"], 0),
			CardNo: kv["cardno"], Granted: granted, Raw: line,
		})
	}
	return out, skipped
}

// CommandResult is one line of a /iclock/devicecmd body: ID=..&Return=..&CMD=..
type CommandResult struct {
	ID     int64
	Return int
	CMD    string
}

// ParseCommandResults reads the device's command replies (one per line).
func ParseCommandResults(body string) []CommandResult {
	var out []CommandResult
	for _, line := range splitLines(body) {
		v, err := url.ParseQuery(line)
		if err != nil {
			continue
		}
		id, err := strconv.ParseInt(strings.TrimSpace(v.Get("ID")), 10, 64)
		if err != nil {
			continue
		}
		out = append(out, CommandResult{ID: id, Return: atoiOr(v.Get("Return"), -1), CMD: v.Get("CMD")})
	}
	return out
}

// DeviceInfo is the INFO query parameter a device sends on getrequest:
// firmware, users, fingerprints, attendance logs, IP, ...
type DeviceInfo struct {
	Firmware   string
	UserCount  int
	PunchCount int
	IP         string
}

// ParseInfo reads the comma separated INFO parameter; ok is false when it is absent.
func ParseInfo(info string) (DeviceInfo, bool) {
	if strings.TrimSpace(info) == "" {
		return DeviceInfo{}, false
	}
	f := strings.Split(info, ",")
	d := DeviceInfo{Firmware: strings.TrimSpace(f[0])}
	if len(f) > 1 {
		d.UserCount = atoiOr(f[1], 0)
	}
	if len(f) > 3 {
		d.PunchCount = atoiOr(f[3], 0)
	}
	if len(f) > 4 {
		d.IP = strings.TrimSpace(f[4])
	}
	return d, true
}

// HandshakeOptions are the values returned on the GET /iclock/cdata handshake.
type HandshakeOptions struct {
	ATTLOGStamp   string
	OPERLOGStamp  string
	ErrorDelay    int
	Delay         int
	TransTimes    string
	TransInterval int
	Realtime      bool
	TZOffsetHours int
}

// HandshakeBody renders the options block a device expects after "GET OPTION FROM: <SN>".
func HandshakeBody(sn string, o HandshakeOptions) string {
	stamp := func(s string) string {
		if s == "" {
			return "None"
		}
		return s
	}
	realtime := 0
	if o.Realtime {
		realtime = 1
	}
	lines := []string{
		"GET OPTION FROM: " + sn,
		"ATTLOGStamp=" + stamp(o.ATTLOGStamp),
		"OPERLOGStamp=" + stamp(o.OPERLOGStamp),
		"ATTPHOTOStamp=None",
		fmt.Sprintf("ErrorDelay=%d", o.ErrorDelay),
		fmt.Sprintf("Delay=%d", o.Delay),
		"TransTimes=" + o.TransTimes,
		fmt.Sprintf("TransInterval=%d", o.TransInterval),
		"TransFlag=TransData AttLog OpLog EnrollUser ChgUser",
		fmt.Sprintf("TimeZone=%d", o.TZOffsetHours),
		fmt.Sprintf("Realtime=%d", realtime),
		"Encrypt=0",
	}
	return strings.Join(lines, "\n") + "\n"
}

// CommandLines renders queued commands for getrequest: "C:<id>:<command>" per line.
func CommandLines(cmds []QueuedCommand) string {
	if len(cmds) == 0 {
		return "OK"
	}
	var b strings.Builder
	for _, c := range cmds {
		fmt.Fprintf(&b, "C:%d:%s\n", c.No, c.Line)
	}
	return b.String()
}

// QueuedCommand is a command line with its device-facing number.
type QueuedCommand struct {
	No   int64
	Line string
}

// UserInfoCommand renders the command that creates or updates a user on the device. Tabs and
// line breaks in the name are replaced, since they delimit the protocol fields.
func UserInfoCommand(pin, name string) string {
	clean := strings.NewReplacer("\t", " ", "\r", " ", "\n", " ").Replace(strings.TrimSpace(name))
	if len(clean) > 24 {
		clean = clean[:24]
	}
	return fmt.Sprintf("DATA UPDATE USERINFO PIN=%s\tName=%s\tPri=0\tPasswd=\tCard=\tGrp=1\tTZ=0000000100000000\tVerify=0", pin, clean)
}

func splitLines(body string) []string {
	raw := strings.Split(strings.ReplaceAll(body, "\r\n", "\n"), "\n")
	out := raw[:0]
	for _, l := range raw {
		if t := strings.TrimRight(l, "\r"); strings.TrimSpace(t) != "" {
			out = append(out, t)
		}
	}
	return out
}

func parseKV(s, sep string) map[string]string {
	out := map[string]string{}
	for _, part := range strings.Split(s, sep) {
		k, v, ok := strings.Cut(part, "=")
		if ok {
			out[strings.TrimSpace(k)] = strings.TrimSpace(v)
		}
	}
	return out
}

func atoiOr(s string, def int) int {
	n, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		return def
	}
	return n
}
