package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestCollectUsers(t *testing.T) {
	passwdPath := filepath.Join(t.TempDir(), "passwd")
	loginDefsPath := filepath.Join(t.TempDir(), "login.defs")
	content := "root:x:0:0:root:/root:/bin/bash\n" +
		"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n" +
		"service:x:998:998:service:/nonexistent:/usr/sbin/nologin\n" +
		"developer:x:1000:1000:Developer:/home/developer:/bin/bash\n"
	if err := os.WriteFile(passwdPath, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(loginDefsPath, []byte("UID_MIN 1000\nUID_MAX 60000\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	inventory, err := collectUsers(passwdPath, loginDefsPath)
	if err != nil {
		t.Fatal(err)
	}
	if inventory.DiscoveredCount != 4 || inventory.TotalCount != 1 || inventory.HumanCount != 1 || inventory.LoginEnabledCount != 1 {
		t.Fatalf("unexpected counts: %+v", inventory)
	}
	if inventory.Users[0].Username != "developer" {
		t.Fatalf("unexpected user: %+v", inventory.Users[0])
	}
}

func TestUsersEndpointRequiresBearerToken(t *testing.T) {
	passwdPath := filepath.Join(t.TempDir(), "passwd")
	if err := os.WriteFile(passwdPath, []byte("root:x:0:0:root:/root:/bin/bash\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := config{
		token:         "0123456789abcdef0123456789abcdef",
		passwdPath:    passwdPath,
		loginDefsPath: filepath.Join(t.TempDir(), "missing-login-defs"),
	}
	server := httptest.NewServer(newHandler(cfg))
	defer server.Close()

	response, err := http.Get(server.URL + "/v1/users")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", response.StatusCode)
	}

	request, err := http.NewRequest(http.MethodGet, server.URL+"/v1/users", nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+cfg.token)
	response, err = http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", response.StatusCode)
	}
	var inventory userInventory
	if err := json.NewDecoder(response.Body).Decode(&inventory); err != nil {
		t.Fatal(err)
	}
	if inventory.TotalCount != 0 {
		t.Fatalf("unexpected inventory: %+v", inventory)
	}
}
