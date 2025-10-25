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

func TestFollowHandler(t *testing.T) {
	tempDir := t.TempDir()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	if err := os.Chdir(tempDir); err != nil {
		t.Fatalf("chdir temp: %v", err)
	}
	t.Cleanup(func() { _ = os.Chdir(wd) })

	// Create an upload key
	keyReq := httptest.NewRequest("POST", "/api/new-upload-key", nil)
	keyRec := httptest.NewRecorder()
	NewUploadKeyHandler(keyRec, keyReq)
	keyResp := keyRec.Result()
	defer keyResp.Body.Close()
	if keyResp.StatusCode != 200 {
		t.Fatalf("new-upload-key failed")
	}
	var keyPayload struct {
		UploadKey string `json:"upload_key"`
	}
	if err := json.NewDecoder(keyResp.Body).Decode(&keyPayload); err != nil {
		t.Fatalf("decode key response: %v", err)
	}

	// Test 1: Follow on non-existent file should return 204 with position 0
	followReq := httptest.NewRequest("GET", "/api/follow?upload_key="+keyPayload.UploadKey, nil)
	followRec := httptest.NewRecorder()
	FollowHandler(followRec, followReq)
	if followRec.Code != 204 {
		t.Fatalf("follow on non-existent file: want 204, got %d", followRec.Code)
	}
	position := followRec.Header().Get("X-Follow-Position")
	if position != "0" {
		t.Fatalf("follow on non-existent file: want position 0, got %s", position)
	}

	// Upload first batch of data
	firstEntries := []string{
		`{"trackerKey":"headset","timestamp":1,"position":{"x":1,"y":2,"z":3}}`,
		`{"trackerKey":"left","timestamp":2,"position":{"x":4,"y":5,"z":6}}`,
	}
	simulateUpload(t, keyPayload.UploadKey, firstEntries)

	// Test 2: First follow should return all lines and position 2
	followReq = httptest.NewRequest("GET", "/api/follow?upload_key="+keyPayload.UploadKey, nil)
	followRec = httptest.NewRecorder()
	FollowHandler(followRec, followReq)
	if followRec.Code != 200 {
		t.Fatalf("first follow: want 200, got %d", followRec.Code)
	}
	position = followRec.Header().Get("X-Follow-Position")
	if position != "2" {
		t.Fatalf("first follow: want position 2, got %s", position)
	}
	firstFollowLines := strings.Split(strings.TrimSpace(followRec.Body.String()), "\n")
	if len(firstFollowLines) != 2 {
		t.Fatalf("first follow: want 2 lines, got %d", len(firstFollowLines))
	}
	// Verify format: lines are already in "index,json_payload" format from CSV file
	for i, line := range firstFollowLines {
		parts := strings.SplitN(line, ",", 2)
		if len(parts) != 2 {
			t.Fatalf("invalid line format: %q", line)
		}
		idx, err := strconv.Atoi(parts[0])
		if err != nil {
			t.Fatalf("invalid index: %v", err)
		}
		if idx != i+1 {
			t.Fatalf("line %d: want index %d, got %d", i, i+1, idx)
		}
	}

	// Test 3: Second follow with position 2 and no new data should return 204
	followReq = httptest.NewRequest("GET", "/api/follow?upload_key="+keyPayload.UploadKey+"&position="+position, nil)
	followRec = httptest.NewRecorder()
	FollowHandler(followRec, followReq)
	if followRec.Code != 204 {
		t.Fatalf("follow with no new data: want 204, got %d", followRec.Code)
	}
	newPosition := followRec.Header().Get("X-Follow-Position")
	if newPosition != "2" {
		t.Fatalf("follow with no new data: want position 2, got %s", newPosition)
	}

	// Upload second batch
	secondEntries := []string{
		`{"trackerKey":"right","timestamp":3,"position":{"x":7,"y":8,"z":9}}`,
		`{"trackerKey":"headset","timestamp":4,"position":{"x":10,"y":11,"z":12}}`,
	}
	simulateUpload(t, keyPayload.UploadKey, secondEntries)

	// Test 4: Third follow with position 2 should return only new lines (3 and 4)
	followReq = httptest.NewRequest("GET", "/api/follow?upload_key="+keyPayload.UploadKey+"&position="+position, nil)
	followRec = httptest.NewRecorder()
	FollowHandler(followRec, followReq)
	if followRec.Code != 200 {
		t.Fatalf("follow with new data: want 200, got %d", followRec.Code)
	}
	position = followRec.Header().Get("X-Follow-Position")
	if position != "4" {
		t.Fatalf("follow with new data: want position 4, got %s", position)
	}
	secondFollowLines := strings.Split(strings.TrimSpace(followRec.Body.String()), "\n")
	if len(secondFollowLines) != 2 {
		t.Fatalf("second follow: want 2 lines, got %d", len(secondFollowLines))
	}
	// Check that indices are 3 and 4
	for i, line := range secondFollowLines {
		parts := strings.SplitN(line, ",", 2)
		idx, _ := strconv.Atoi(parts[0])
		expectedIdx := i + 3
		if idx != expectedIdx {
			t.Fatalf("second follow line %d: want index %d, got %d", i, expectedIdx, idx)
		}
	}

	// Test 5: Fourth follow with position 4 should return 204 again
	followReq = httptest.NewRequest("GET", "/api/follow?upload_key="+keyPayload.UploadKey+"&position="+position, nil)
	followRec = httptest.NewRecorder()
	FollowHandler(followRec, followReq)
	if followRec.Code != 204 {
		t.Fatalf("final follow with no new data: want 204, got %d", followRec.Code)
	}
	newPosition = followRec.Header().Get("X-Follow-Position")
	if newPosition != "4" {
		t.Fatalf("final follow with no new data: want position 4, got %s", newPosition)
	}
}
