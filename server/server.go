package server

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"
)

var uploadKeys = []string{}
var uploadKeysMutex sync.Mutex

type DataEntry struct {
	TrackerKey string `json:"trackerKey"`
	Timestamp  int64  `json:"timestamp"`
	Position   struct {
		X float64 `json:"x"`
		Y float64 `json:"y"`
		Z float64 `json:"z"`
	} `json:"position"`
}

const (
	uploadDir             = "uploads"
	uploadKeyHexLength    = 128
	uploadKeyPrefixLength = 16
	uploadNameWordCount   = 4
)

var uploadNameWords = []string{
	"correct",
	"battery",
	"horse",
	"staple",
	"amber",
	"beacon",
	"celestial",
	"delta",
	"ember",
	"fable",
	"galaxy",
	"harbor",
	"ionic",
	"jungle",
	"keystone",
	"lantern",
	"meadow",
	"nebula",
	"opal",
	"prairie",
	"quartz",
	"ripple",
	"solstice",
	"tundra",
	"uplink",
	"voyage",
	"whisper",
	"xenon",
	"yonder",
	"zephyr",
	"aurora",
	"cascade",
	"dawn",
	"evergreen",
	"frost",
	"glimmer",
	"horizon",
	"island",
	"juniper",
	"kestrel",
	"lilac",
	"meridian",
	"nimbus",
	"onyx",
	"pioneer",
	"quiver",
	"resonance",
	"saffron",
	"topaz",
}

func generateUploadKey() (string, error) {
	buf := make([]byte, uploadKeyHexLength/2)
	if _, err := rand.Read(buf); err != nil {
		return "", fmt.Errorf("generate upload key: %w", err)
	}

	return hex.EncodeToString(buf), nil
}

func uploadNameFromKey(uploadKey string) string {
	if len(uploadNameWords) == 0 {
		return "upload"
	}

	normalized := strings.ToLower(strings.TrimSpace(uploadKey))
	keyBytes, err := hex.DecodeString(normalized)
	if err != nil || len(keyBytes) < uploadNameWordCount*2 {
		return "upload"
	}

	words := make([]string, uploadNameWordCount)
	for i := 0; i < uploadNameWordCount; i++ {
		offset := i * 2
		value := int(keyBytes[offset])<<8 | int(keyBytes[offset+1])
		index := value % len(uploadNameWords)
		words[i] = uploadNameWords[index]
	}

	return strings.Join(words, " ")
}

func saveUpload(uploadKey, userAgent string, receivedAt time.Time, lines []string) (filePath string, err error) {
	uploadName := uploadNameFromKey(uploadKey)

	if err = os.MkdirAll(uploadDir, 0o755); err != nil {
		return "", fmt.Errorf("create upload directory: %w", err)
	}

	filename := fmt.Sprintf("%s_%s.csv", uploadName, uploadKey)
	filePath = filepath.Join(uploadDir, filename)

	file, err := os.OpenFile(filePath, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return "", fmt.Errorf("open upload file: %w", err)
	}

	cleanupOnErr := false
	defer func() {
		if cerr := file.Close(); err == nil && cerr != nil {
			err = cerr
		}
		if err != nil && cleanupOnErr {
			if removeErr := os.Remove(filePath); removeErr != nil {
				log.Printf("failed to remove incomplete upload file %s: %v", filePath, removeErr)
			}
		}
	}()

	info, err := file.Stat()
	if err != nil {
		return "", fmt.Errorf("stat upload file: %w", err)
	}

	isNew := info.Size() == 0
	if isNew {
		cleanupOnErr = true
	}

	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return "", fmt.Errorf("seek upload file to start: %w", err)
	}

	existingRecords := 0
	if !isNew {
		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 0, 1024), 16*1024*1024)
		if scanner.Scan() {
			// skip metadata line
		}
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			existingRecords++
		}
		if err := scanner.Err(); err != nil {
			return "", fmt.Errorf("scan existing upload file: %w", err)
		}
	}

	needsTrailingNewline := false
	if !isNew && info.Size() > 0 {
		lastByte := make([]byte, 1)
		if _, err := file.ReadAt(lastByte, info.Size()-1); err == nil && lastByte[0] != '\n' {
			needsTrailingNewline = true
		}
	}

	if _, err = file.Seek(0, io.SeekEnd); err != nil {
		return "", fmt.Errorf("seek upload file to end: %w", err)
	}

	writer := bufio.NewWriter(file)

	if isNew {
		metadata := map[string]any{
			"upload_key":  uploadKey,
			"upload_name": uploadName,
			"user_agent":  userAgent,
			"received_at": receivedAt.Format(time.RFC3339Nano),
		}
		metadataJSON, err := json.Marshal(metadata)
		if err != nil {
			return "", fmt.Errorf("encode metadata: %w", err)
		}
		if _, err = writer.Write(metadataJSON); err != nil {
			return "", fmt.Errorf("write metadata: %w", err)
		}
		if err = writer.WriteByte('\n'); err != nil {
			return "", fmt.Errorf("write metadata newline: %w", err)
		}
	} else if needsTrailingNewline {
		if err = writer.WriteByte('\n'); err != nil {
			return "", fmt.Errorf("write separator newline: %w", err)
		}
	}

	startIndex := existingRecords + 1
	for i, line := range lines {
		if _, err = writer.WriteString(strconv.Itoa(startIndex + i)); err != nil {
			return "", fmt.Errorf("write record %d index: %w", startIndex+i, err)
		}
		if err = writer.WriteByte(','); err != nil {
			return "", fmt.Errorf("write record %d separator: %w", startIndex+i, err)
		}
		if _, err = writer.WriteString(line); err != nil {
			return "", fmt.Errorf("write record %d payload: %w", startIndex+i, err)
		}
		if err = writer.WriteByte('\n'); err != nil {
			return "", fmt.Errorf("write record newline %d: %w", startIndex+i, err)
		}
	}

	if err = writer.Flush(); err != nil {
		return "", fmt.Errorf("flush upload data: %w", err)
	}

	cleanupOnErr = false
	return filePath, nil
}

func NewUploadKeyHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		panic("only POST allowed")
	}

	uploadKey, err := generateUploadKey()
	if err != nil {
		log.Printf("failed to generate upload key: %v", err)
		http.Error(w, "failed to generate upload key", http.StatusInternalServerError)
		return
	}

	func() {
		uploadKeysMutex.Lock()
		defer uploadKeysMutex.Unlock()
		uploadKeys = append(uploadKeys, uploadKey)
	}()

	uploadName := uploadNameFromKey(uploadKey)
	log.Printf("generated upload key upload_name=%q upload_key=%q", uploadName, uploadKey)

	w.Header().Set("Content-Type", "application/json")
	response := map[string]any{
		"status":     "ok",
		"name":       uploadName,
		"upload_key": uploadKey,
	}

	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("failed to write new upload key response: %v", err)
	}
}

func UploadHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		panic("only POST allowed")
	}

	uploadKey := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("upload_key")))
	if uploadKey == "" {
		http.Error(w, "missing upload_key query parameter", http.StatusBadRequest)
		return
	}

	if len(uploadKey) != uploadKeyHexLength {
		http.Error(w, fmt.Sprintf("invalid upload_key length: expected %d-character hex string", uploadKeyHexLength), http.StatusBadRequest)
		return
	}

	if _, err := hex.DecodeString(uploadKey); err != nil {
		http.Error(w, "invalid upload_key format: must be hexadecimal", http.StatusBadRequest)
		return
	}

	validUploadKey := func() bool {
		uploadKeysMutex.Lock()
		defer uploadKeysMutex.Unlock()
		return slices.Contains(uploadKeys, uploadKey)
	}()
	if !validUploadKey {
		http.Error(w, "invalid upload_key value: generate another one and try again", http.StatusBadRequest)
		return
	}

	uploadName := uploadNameFromKey(uploadKey)

	userAgent := r.Header.Get("User-Agent")
	receivedAt := time.Now().UTC()

	scanner := bufio.NewScanner(r.Body)
	defer r.Body.Close()

	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 16*1024*1024)

	records := 0
	lines := make([]string, 0, 200) // approx. 10 per second, and save every 10 seconds (and add some buffer for uncertainty)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		lineNumber := records + 1

		var payload json.RawMessage
		if err := json.Unmarshal([]byte(line), &payload); err != nil {
			http.Error(w, fmt.Sprintf("invalid JSON on line %d: %v", lineNumber, err), http.StatusBadRequest)
			return
		}

		lines = append(lines, line)
		records++
		log.Printf("upload record upload_key=%q upload_name=%q line=%d data=%s", uploadKey, uploadName, lineNumber, line)
	}

	if err := scanner.Err(); err != nil {
		http.Error(w, fmt.Sprintf("error reading request body: %v", err), http.StatusBadRequest)
		return
	}

	filePath, err := saveUpload(uploadKey, userAgent, receivedAt, lines)
	if err != nil {
		log.Printf("failed to store upload: %v", err)
		http.Error(w, "failed to store upload", http.StatusInternalServerError)
		return
	}

	log.Printf(
		"upload received upload_key=%q upload_name=%q user_agent=%q received_at=%s records=%d saved_to=%s",
		uploadKey,
		uploadName,
		userAgent,
		receivedAt.Format(time.RFC3339Nano),
		records,
		filePath,
	)

	w.Header().Set("Content-Type", "application/json")
	response := map[string]any{
		"status":      "ok",
		"records":     records,
		"received_at": receivedAt.Format(time.RFC3339Nano),
		"file_path":   filePath,
		"upload_name": uploadName,
	}

	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("failed to write response: %v", err)
	}
}
