package main

import (
	"bufio"
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const version = "0.1.0"

type config struct {
	listenAddress string
	token         string
	passwdPath    string
	loginDefsPath string
	tlsCertFile   string
	tlsKeyFile    string
}

type linuxUser struct {
	Username     string `json:"username"`
	UID          int    `json:"uid"`
	GID          int    `json:"gid"`
	Comment      string `json:"comment"`
	Home         string `json:"home"`
	Shell        string `json:"shell"`
	LoginEnabled bool   `json:"login_enabled"`
}

type userInventory struct {
	Hostname          string      `json:"hostname"`
	CollectedAt       string      `json:"collected_at"`
	DiscoveredCount   int         `json:"discovered_count"`
	TotalCount        int         `json:"total_count"`
	HumanCount        int         `json:"human_count"`
	LoginEnabledCount int         `json:"login_enabled_count"`
	Users             []linuxUser `json:"users"`
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatal(err)
	}

	server := &http.Server{
		Addr:              cfg.listenAddress,
		Handler:           newHandler(cfg),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	serverErrors := make(chan error, 1)
	go func() {
		log.Printf("linux account agent %s listening on %s", version, cfg.listenAddress)
		if cfg.tlsCertFile != "" {
			serverErrors <- server.ListenAndServeTLS(cfg.tlsCertFile, cfg.tlsKeyFile)
			return
		}
		serverErrors <- server.ListenAndServe()
	}()

	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
	select {
	case sig := <-signals:
		log.Printf("received %s, shutting down", sig)
	case err := <-serverErrors:
		if !errors.Is(err, http.ErrServerClosed) {
			log.Fatal(err)
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		log.Printf("graceful shutdown failed: %v", err)
	}
}

func loadConfig() (config, error) {
	cfg := config{
		listenAddress: envOrDefault("INFRAOPS_AGENT_LISTEN", "127.0.0.1:39110"),
		token:         strings.TrimSpace(os.Getenv("INFRAOPS_AGENT_TOKEN")),
		passwdPath:    envOrDefault("INFRAOPS_AGENT_PASSWD_FILE", "/etc/passwd"),
		loginDefsPath: envOrDefault("INFRAOPS_AGENT_LOGIN_DEFS_FILE", "/etc/login.defs"),
		tlsCertFile:   strings.TrimSpace(os.Getenv("INFRAOPS_AGENT_TLS_CERT_FILE")),
		tlsKeyFile:    strings.TrimSpace(os.Getenv("INFRAOPS_AGENT_TLS_KEY_FILE")),
	}
	if len(cfg.token) < 32 {
		return config{}, errors.New("INFRAOPS_AGENT_TOKEN must contain at least 32 characters")
	}
	if (cfg.tlsCertFile == "") != (cfg.tlsKeyFile == "") {
		return config{}, errors.New("TLS certificate and key must be configured together")
	}
	return cfg, nil
}

func envOrDefault(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func newHandler(cfg config) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "version": version})
	})
	mux.Handle("GET /v1/users", bearerAuth(cfg.token, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		inventory, err := collectUsers(cfg.passwdPath, cfg.loginDefsPath)
		if err != nil {
			log.Printf("account inventory failed: %v", err)
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "account inventory failed"})
			return
		}
		writeJSON(w, http.StatusOK, inventory)
	})))
	return requestLogger(mux)
}

func bearerAuth(expectedToken string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		scheme, token, ok := strings.Cut(r.Header.Get("Authorization"), " ")
		valid := ok && strings.EqualFold(scheme, "Bearer") &&
			subtle.ConstantTimeCompare([]byte(token), []byte(expectedToken)) == 1
		if !valid {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
			return
		}
		next.ServeHTTP(w, r)
	})
}

func requestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("method=%s path=%s duration_ms=%d", r.Method, r.URL.Path, time.Since(started).Milliseconds())
	})
}

func collectUsers(passwdPath, loginDefsPath string) (userInventory, error) {
	uidMin, uidMax, err := readUIDRange(loginDefsPath)
	if err != nil {
		return userInventory{}, err
	}
	file, err := os.Open(passwdPath)
	if err != nil {
		return userInventory{}, fmt.Errorf("open passwd file: %w", err)
	}
	defer file.Close()

	users := make([]linuxUser, 0, 32)
	discoveredCount := 0
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Split(line, ":")
		if len(fields) != 7 {
			return userInventory{}, fmt.Errorf("invalid passwd entry with %d fields", len(fields))
		}
		discoveredCount++
		uid, err := strconv.Atoi(fields[2])
		if err != nil {
			return userInventory{}, fmt.Errorf("invalid uid for %s: %w", fields[0], err)
		}
		gid, err := strconv.Atoi(fields[3])
		if err != nil {
			return userInventory{}, fmt.Errorf("invalid gid for %s: %w", fields[0], err)
		}
		if uid < uidMin || uid > uidMax {
			continue
		}
		users = append(users, linuxUser{
			Username:     fields[0],
			UID:          uid,
			GID:          gid,
			Comment:      fields[4],
			Home:         fields[5],
			Shell:        fields[6],
			LoginEnabled: isLoginShell(fields[6]),
		})
	}
	if err := scanner.Err(); err != nil {
		return userInventory{}, fmt.Errorf("read passwd file: %w", err)
	}

	sort.Slice(users, func(i, j int) bool {
		if users[i].UID == users[j].UID {
			return users[i].Username < users[j].Username
		}
		return users[i].UID < users[j].UID
	})
	hostname, err := os.Hostname()
	if err != nil {
		return userInventory{}, fmt.Errorf("read hostname: %w", err)
	}
	inventory := userInventory{
		Hostname:        hostname,
		CollectedAt:     time.Now().UTC().Format(time.RFC3339),
		DiscoveredCount: discoveredCount,
		TotalCount:      len(users),
		HumanCount:      len(users),
		Users:           users,
	}
	for _, user := range users {
		if user.LoginEnabled {
			inventory.LoginEnabledCount++
		}
	}
	return inventory, nil
}

func readUIDRange(path string) (int, int, error) {
	uidMin, uidMax := 1000, 60000
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return uidMin, uidMax, nil
	}
	if err != nil {
		return 0, 0, fmt.Errorf("open login.defs: %w", err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 || strings.HasPrefix(fields[0], "#") {
			continue
		}
		value, parseErr := strconv.Atoi(fields[1])
		if parseErr != nil {
			continue
		}
		switch fields[0] {
		case "UID_MIN":
			uidMin = value
		case "UID_MAX":
			uidMax = value
		}
	}
	if err := scanner.Err(); err != nil {
		return 0, 0, fmt.Errorf("read login.defs: %w", err)
	}
	return uidMin, uidMax, nil
}

func isLoginShell(shell string) bool {
	value := strings.TrimSpace(shell)
	if value == "" {
		return false
	}
	for _, suffix := range []string{"/nologin", "/false", "/sync", "/shutdown", "/halt"} {
		if strings.HasSuffix(value, suffix) {
			return false
		}
	}
	return true
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		log.Printf("write response failed: %v", err)
	}
}
