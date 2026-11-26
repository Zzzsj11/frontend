package main

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type Source struct {
	URL   string
	Bytes int64
	Name  string
}
type Spec struct {
	Index    int
	Sources  []Source
	Parts    []string
	Markdown string
}
type Config struct {
	PartSize int
	InFlight int
	Jobs     []Spec
	Limit    int64
}
type Part struct {
	ETag    string
	Size    int
	QoS     bool
	Failure string
}
type Result struct {
	Index    int
	Download int64
	GetQoS   int
	Parts    []Part
	Failure  string
}

var client = &http.Client{
	Transport: &http.Transport{MaxIdleConns: 256, MaxIdleConnsPerHost: 256, MaxConnsPerHost: 256,
		DialContext:         (&net.Dialer{Timeout: 8 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		TLSHandshakeTimeout: 8 * time.Second, IdleConnTimeout: 60 * time.Second},
	Timeout:       180 * time.Second,
	CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse },
}
var buffers sync.Pool
var progress = json.NewEncoder(os.Stdout)

func upload(url string, payload []byte) Part {
	req, err := http.NewRequest(http.MethodPut, url, bytes.NewReader(payload))
	if err != nil {
		return Part{Failure: "part request setup"}
	}
	response, err := client.Do(req)
	if err != nil {
		return Part{Failure: "part transport"}
	}
	defer response.Body.Close()
	io.Copy(io.Discard, io.LimitReader(response.Body, 8192))
	if response.StatusCode != 200 {
		return Part{Failure: fmt.Sprintf("part HTTP %d", response.StatusCode)}
	}
	etag := strings.Trim(response.Header.Get("ETag"), "\"")
	if etag == "" {
		return Part{Failure: "part ETag missing"}
	}
	return Part{ETag: etag, Size: len(payload), QoS: response.Header.Get("x-oss-qos-delay-time") != ""}
}

type Pending struct {
	urls     []string
	partSize int
	buf      []byte
	finished []Part
	wg       sync.WaitGroup
	slots    chan struct{}
	number   int
	limit    int64
	total    int64
}

func (s *Pending) submit() error {
	if len(s.buf) == 0 {
		return nil
	}
	if s.number >= len(s.urls) {
		return fmt.Errorf("no signed part available")
	}
	s.slots <- struct{}{}
	n, data := s.number, s.buf
	s.number++
	s.buf = nil
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		defer func() { buffers.Put(data[:0]); <-s.slots }()
		s.finished[n] = upload(s.urls[n], data)
	}()
	return nil
}

func (s *Pending) Write(p []byte) (int, error) {
	length := len(p)
	if s.total+int64(length) > s.limit {
		return 0, fmt.Errorf("archive size limit")
	}
	s.total += int64(length)
	for len(p) > 0 {
		if s.buf == nil {
			if reuse := buffers.Get(); reuse != nil {
				s.buf = reuse.([]byte)
			}
			if s.buf == nil {
				s.buf = make([]byte, 0, s.partSize)
			}
		}
		amount := min(len(p), s.partSize-len(s.buf))
		s.buf = append(s.buf, p[:amount]...)
		p = p[amount:]
		if len(s.buf) == s.partSize {
			if err := s.submit(); err != nil {
				return length - len(p), err
			}
		}
	}
	return length, nil
}

func runJob(task Spec, config Config) (result Result) {
	result.Index = task.Index
	sink := &Pending{urls: task.Parts, partSize: config.PartSize, finished: make([]Part, len(task.Parts)), slots: make(chan struct{}, config.InFlight), limit: config.Limit}
	defer sink.wg.Wait()
	writer := zip.NewWriter(sink)
	buffer := make([]byte, 1<<20)
	for i, source := range task.Sources {
		response, err := client.Get(source.URL)
		if err != nil {
			result.Failure = "source transport"
			return
		}
		if response.StatusCode != 200 {
			response.Body.Close()
			result.Failure = fmt.Sprintf("source HTTP %d", response.StatusCode)
			return
		}
		if response.Header.Get("x-oss-qos-delay-time") != "" {
			result.GetQoS++
		}
		member, err := writer.CreateHeader(&zip.FileHeader{Name: source.Name, Method: zip.Store})
		if err != nil {
			response.Body.Close()
			result.Failure = "ZIP member setup"
			return
		}
		n, err := io.CopyBuffer(member, io.LimitReader(response.Body, 500*1024*1024+1), buffer)
		response.Body.Close()
		if err != nil || n > 500*1024*1024 || (response.ContentLength >= 0 && n != response.ContentLength) {
			result.Failure = "source length or ZIP write"
			return
		}
		result.Download += n
		if progress.Encode(map[string]int64{"processed": int64(i + 1), "bytes": result.Download}) != nil {
			result.Failure = "progress pipe"
			return
		}
	}
	member, err := writer.Create("prompts.md")
	if err != nil {
		result.Failure = "Markdown setup"
		return
	}
	if _, err = io.WriteString(member, task.Markdown); err != nil {
		result.Failure = "Markdown write"
		return
	}
	if err := writer.Close(); err != nil {
		result.Failure = "ZIP finish"
		return
	}
	if err := sink.submit(); err != nil {
		result.Failure = "multipart finish"
		return
	}
	sink.wg.Wait()
	result.Parts = sink.finished[:sink.number]
	for _, part := range result.Parts {
		if part.Failure != "" {
			result.Failure = part.Failure
			break
		}
	}
	return
}

func main() {
	var config Config
	if json.NewDecoder(os.Stdin).Decode(&config) != nil || len(config.Jobs) != 1 {
		os.Exit(2)
	}
	result := runJob(config.Jobs[0], config)
	progress.Encode(result)
}
