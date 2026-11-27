package main

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestFailedPartCancelsSourceAndSkipsLaterObjects(t *testing.T) {
	var later atomic.Int32
	cancelled := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/part":
			http.Error(w, "synthetic upload failure", http.StatusServiceUnavailable)
		case "/slow":
			w.WriteHeader(http.StatusOK)
			_, _ = io.Copy(w, bytes.NewReader(bytes.Repeat([]byte("v"), 64*1024)))
			w.(http.Flusher).Flush()
			select {
			case <-r.Context().Done():
				close(cancelled)
			case <-time.After(5 * time.Second):
			}
		default:
			later.Add(1)
		}
	}))
	defer server.Close()
	job := Spec{Sources: []Source{{URL: server.URL + "/slow", Name: "first.mp4"}, {URL: server.URL + "/later", Name: "later.mp4"}}}
	for i := 0; i < 128; i++ {
		job.Parts = append(job.Parts, server.URL+"/part")
	}
	result := runJob(job, Config{PartSize: 1024, InFlight: 1, Limit: 1024 * 1024})
	if !strings.Contains(result.Failure, "part HTTP 503") || later.Load() != 0 {
		t.Fatalf("failure=%q later GETs=%d", result.Failure, later.Load())
	}
	select {
	case <-cancelled:
	case <-time.After(time.Second):
		t.Fatal("source GET was not cancelled")
	}
}
