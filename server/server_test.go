package server

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestUploadFlow(t *testing.T) {
	tempDir := t.TempDir()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	if err := os.Chdir(tempDir); err != nil {
		t.Fatalf("chdir temp: %v", err)
	}
	t.Cleanup(func() { _ = os.Chdir(wd) })

	keyReq := httptest.NewRequest("POST", "/api/new-upload-key", nil)
	keyRec := httptest.NewRecorder()
	NewUploadKeyHandler(keyRec, keyReq)
	keyResp := keyRec.Result()
	defer keyResp.Body.Close()
	if keyResp.StatusCode != 200 {
		body, _ := io.ReadAll(keyResp.Body)
		t.Fatalf("new-upload-key status = %d body=%s", keyResp.StatusCode, body)
	}
	var keyPayload struct {
		UploadKey string `json:"upload_key"`
		Name      string `json:"name"`
	}
	if err := json.NewDecoder(keyResp.Body).Decode(&keyPayload); err != nil {
		t.Fatalf("decode upload key response: %v", err)
	}
	if keyPayload.UploadKey == "" {
		t.Fatalf("empty upload key")
	}

	firstEntries := []string{
		`{"trackerKey":"headset","timestamp":1,"position":{"x":1,"y":2,"z":3}}`,
		`{"trackerKey":"left","timestamp":2,"position":{"x":4,"y":5,"z":6}}`,
	}
	filePath := simulateUpload(t, keyPayload.UploadKey, firstEntries)
	fullPath := filepath.Join(tempDir, filePath)

	metaLine, metaMap, lines := readUploadFile(t, fullPath)
	expectedName := uploadNameFromKey(keyPayload.UploadKey)
	if metaMap["upload_key"] != keyPayload.UploadKey {
		t.Fatalf("metadata upload_key = %v, want %s", metaMap["upload_key"], keyPayload.UploadKey)
	}
	if metaMap["upload_name"] != expectedName {
		t.Fatalf("metadata upload_name = %v, want %s", metaMap["upload_name"], expectedName)
	}
	assertRecords(t, lines, firstEntries)

	secondEntries := []string{
		`{"trackerKey":"right","timestamp":3,"position":{"x":7,"y":8,"z":9}}`,
	}
	secondPath := simulateUpload(t, keyPayload.UploadKey, secondEntries)
	if secondPath != filePath {
		t.Fatalf("file path changed between uploads: %q vs %q", filePath, secondPath)
	}

	metaLine2, _, lines2 := readUploadFile(t, fullPath)
	if metaLine2 != metaLine {
		t.Fatalf("metadata line changed between uploads")
	}
	combined := append(append([]string{}, firstEntries...), secondEntries...)
	assertRecords(t, lines2, combined)
}

func simulateUpload(t *testing.T, key string, entries []string) string {
	t.Helper()
	body := bytes.NewBufferString(strings.Join(entries, "\n"))
	req := httptest.NewRequest("POST", "/api/upload?upload_key="+url.QueryEscape(key), body)
	req.Header.Set("Content-Type", "application/x-ndjson")
	req.Header.Set("User-Agent", "test-agent")

	rec := httptest.NewRecorder()
	UploadHandler(rec, req)
	resp := rec.Result()
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		t.Fatalf("upload status = %d body=%s", resp.StatusCode, data)
	}
	var payload struct {
		FilePath string `json:"file_path"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		t.Fatalf("decode upload response: %v", err)
	}
	if payload.FilePath == "" {
		t.Fatalf("empty file path in response")
	}
	return payload.FilePath
}

func readUploadFile(t *testing.T, path string) (string, map[string]any, []string) {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open upload file: %v", err)
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	if !scanner.Scan() {
		t.Fatalf("missing metadata line")
	}
	metaLine := scanner.Text()
	var metadata map[string]any
	if err := json.Unmarshal([]byte(metaLine), &metadata); err != nil {
		t.Fatalf("metadata json: %v", err)
	}
	var records []string
	for scanner.Scan() {
		records = append(records, scanner.Text())
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scanner error: %v", err)
	}
	return metaLine, metadata, records
}

func assertRecords(t *testing.T, lines []string, expected []string) {
	t.Helper()
	if len(lines) != len(expected) {
		t.Fatalf("records count = %d, want %d", len(lines), len(expected))
	}
	for i, line := range lines {
		parts := strings.SplitN(line, ",", 2)
		if len(parts) != 2 {
			t.Fatalf("invalid record line: %q", line)
		}
		idx, err := strconv.Atoi(parts[0])
		if err != nil {
			t.Fatalf("invalid index %q: %v", parts[0], err)
		}
		if idx != i+1 {
			t.Fatalf("record index = %d, want %d", idx, i+1)
		}
		if parts[1] != expected[i] {
			t.Fatalf("record payload = %s, want %s", parts[1], expected[i])
		}
	}
}
