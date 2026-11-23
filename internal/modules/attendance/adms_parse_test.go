package attendance

import (
	"strings"
	"testing"
	"time"
)

// Recorded shapes of ZKTeco PUSH traffic (SenseFace / MB series, push protocol 2.4).
const (
	recordedATTLOG = "1\t2026-11-23 07:58:12\t0\t15\t0\t0\t0\t0\t0\t0\r\n" +
		"1024\t2026-11-23 08:16:40\t0\t1\t\t0\t0\t0\t0\t0\r\n" +
		"1\t2026-11-23 17:02:55\t1\t15\t0\t0\t0\t0\t0\t0\r\n" +
		"garbage line\r\n" +
		"\r\n"
	recordedOPERLOG = "OPLOG 4\t0\t2026-11-23 08:00:00\t0\t0\t0\t0\n" +
		"USER PIN=1\tName=Jane Wanjiru\tPri=0\tPasswd=\tCard=\tGrp=1\tTZ=0000000100000000\tVerify=0\n" +
		"USER PIN=1024\tName=Otieno\tPri=14\tPasswd=\tCard=12345\tGrp=1\n" +
		"FP PIN=1\tFID=6\tSize=1024\tValid=1\tTMP=AAAA\n"
	recordedRTLog = "time=2026-11-23 08:01:03\tpin=1\tcardno=0\teventaddr=1\tevent=0\tinoutstatus=0\tverifytype=15\tindex=12\n" +
		"time=2026-11-23 08:05:44\tpin=0\tcardno=998877\teventaddr=1\tevent=27\tinoutstatus=0\tverifytype=4\tindex=13\n" +
		"time=2026-11-23 08:06:00\tpin=0\tcardno=0\teventaddr=1\tevent=200\tinoutstatus=0\tverifytype=200\tindex=14\n"
)

func TestParseATTLOG(t *testing.T) {
	loc := nairobi(t)
	got, skipped := ParseATTLOG(recordedATTLOG, loc)
	if len(got) != 3 || skipped != 1 {
		t.Fatalf("parsed %d skipped %d, want 3 and 1", len(got), skipped)
	}
	if got[0].PIN != "1" || got[0].Verify != 15 || got[0].Status != 0 {
		t.Fatalf("first punch %+v", got[0])
	}
	// Device wall-clock time in Nairobi is 04:58:12 UTC.
	if want := time.Date(2026, 11, 23, 4, 58, 12, 0, time.UTC); !got[0].At.Equal(want) {
		t.Fatalf("time %v, want %v", got[0].At.UTC(), want)
	}
	if got[2].Status != stateOut {
		t.Fatalf("check-out status %d, want 1", got[2].Status)
	}
}

func TestParseOPERLOG(t *testing.T) {
	ol := ParseOPERLOG(recordedOPERLOG)
	if len(ol.Users) != 2 || ol.Ops != 1 || ol.Other != 1 {
		t.Fatalf("users %d ops %d other %d", len(ol.Users), ol.Ops, ol.Other)
	}
	if ol.Users[0].Name != "Jane Wanjiru" || ol.Users[1].Pri != 14 || ol.Users[1].Card != "12345" {
		t.Fatalf("users %+v", ol.Users)
	}
}

func TestParseRTLog(t *testing.T) {
	got, skipped := ParseRTLog(recordedRTLog, nairobi(t))
	if len(got) != 2 || skipped != 1 { // the door-sensor event (200) is not an access event
		t.Fatalf("parsed %d skipped %d, want 2 and 1", len(got), skipped)
	}
	if !got[0].Granted || got[0].PIN != "1" || got[0].Verify != 15 {
		t.Fatalf("granted event %+v", got[0])
	}
	if got[1].Granted || got[1].PIN != "" || got[1].CardNo != "998877" || got[1].Event != 27 {
		t.Fatalf("denied event %+v", got[1])
	}
}

func TestHandshakeBody(t *testing.T) {
	body := HandshakeBody("CKJF213260123", HandshakeOptions{
		OPERLOGStamp: "9999", ErrorDelay: 30, Delay: 10, TransTimes: "00:00;14:05",
		TransInterval: 1, Realtime: true, TZOffsetHours: 3,
	})
	for _, want := range []string{
		"GET OPTION FROM: CKJF213260123\n", "ATTLOGStamp=None\n", "OPERLOGStamp=9999\n",
		"ErrorDelay=30\n", "Delay=10\n", "TransTimes=00:00;14:05\n", "TransInterval=1\n",
		"TransFlag=", "Realtime=1\n", "Encrypt=0\n", "TimeZone=3\n",
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("handshake lacks %q:\n%s", want, body)
		}
	}
	if !strings.HasPrefix(body, "GET OPTION FROM:") {
		t.Fatal("handshake must start with GET OPTION FROM")
	}
}

// A command goes out as C:<no>:<line> and comes back as ID=<no>&Return=..&CMD=..
func TestCommandRoundTrip(t *testing.T) {
	if CommandLines(nil) != "OK" {
		t.Fatal("no commands must answer OK")
	}
	out := CommandLines([]QueuedCommand{{No: 7, Line: UserInfoCommand("1024", "Otieno\tOchieng")}, {No: 8, Line: "REBOOT"}})
	want := "C:7:DATA UPDATE USERINFO PIN=1024\tName=Otieno Ochieng\tPri=0\tPasswd=\tCard=\tGrp=1\tTZ=0000000100000000\tVerify=0\nC:8:REBOOT\n"
	if out != want {
		t.Fatalf("command lines:\n%q\nwant\n%q", out, want)
	}
	res := ParseCommandResults("ID=7&Return=0&CMD=DATA\nID=8&Return=-1002&CMD=REBOOT\nnonsense\n")
	if len(res) != 2 || res[0].ID != 7 || res[0].Return != 0 || res[1].Return != -1002 || res[1].CMD != "REBOOT" {
		t.Fatalf("results %+v", res)
	}
}

func TestParseInfo(t *testing.T) {
	d, ok := ParseInfo("Ver 8.0.4.2-20210909,12,10,3456,192.168.1.201,10,7,12,0,111")
	if !ok || d.Firmware != "Ver 8.0.4.2-20210909" || d.UserCount != 12 || d.PunchCount != 3456 || d.IP != "192.168.1.201" {
		t.Fatalf("info %+v ok=%v", d, ok)
	}
	if _, ok := ParseInfo(""); ok {
		t.Fatal("empty INFO must not parse")
	}
}
