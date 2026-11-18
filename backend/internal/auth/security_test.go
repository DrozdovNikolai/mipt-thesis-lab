package auth

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"north55/backend/internal/platform"
)

func TestPasslibPasswordCompatibility(t *testing.T) {
	// Generated independently by Passlib 1.7.4.
	const reference = "$pbkdf2-sha256$29000$bm9ydGg1NS1maXh0dXJlISE$U7TmcS6UcYXa.taXTcr2ZoYpxtM7Q9r1rwutcHR2kTY"
	if !VerifyPassword("admin123", reference) {
		t.Fatal("cannot verify existing Passlib password")
	}
	for _, password := range []string{"Admin123", "admin123 ", "", "пароль123"} {
		if VerifyPassword(password, reference) {
			t.Fatalf("accepted wrong password %q", password)
		}
	}
	for _, hash := range []string{"", reference + "!", "$pbkdf2-sha256$0$AA$AA", "$pbkdf2-sha256$999999999999$AA$AA"} {
		if VerifyPassword("admin123", hash) {
			t.Fatalf("accepted malformed hash %q", hash)
		}
	}
}
func TestTokensEnforceTypeSignatureTimeAndClaims(t *testing.T) {
	cfg := platform.Config{AccessSecret: "access-secret", RefreshSecret: "refresh-secret", JWTAlgorithm: "HS256", AccessTTL: 30 * time.Minute, RefreshTTL: 7 * 24 * time.Hour}
	subject, sid, jti := uuid.New(), uuid.New(), uuid.New()
	access, err := SignToken(cfg, subject, sid, jti, "access", time.Now().UTC())
	if err != nil {
		t.Fatal(err)
	}
	data, err := DecodeToken(cfg, access, "access")
	if err != nil || data != (TokenData{subject, sid, jti}) {
		t.Fatalf("decode: %+v %v", data, err)
	}
	if _, err = DecodeToken(cfg, access, "refresh"); err == nil {
		t.Fatal("access token accepted as refresh")
	}
	changed := cfg
	changed.AccessSecret = "wrong-secret"
	if _, err = DecodeToken(changed, access, "access"); err == nil {
		t.Fatal("invalid signature accepted")
	}
	expired, _ := SignToken(cfg, subject, sid, jti, "access", time.Now().Add(-time.Hour))
	if _, err = DecodeToken(cfg, expired, "access"); err == nil {
		t.Fatal("expired token accepted")
	}
	future, _ := SignToken(cfg, subject, sid, jti, "access", time.Now().Add(time.Minute))
	if _, err = DecodeToken(cfg, future, "access"); err == nil {
		t.Fatal("future token accepted")
	}
}
