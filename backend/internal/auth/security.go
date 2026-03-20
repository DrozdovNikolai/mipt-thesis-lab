package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"golang.org/x/crypto/pbkdf2"
	"north55/backend/internal/platform"
)

var passlibEncoding = base64.NewEncoding("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789./").WithPadding(base64.NoPadding)

func VerifyPassword(password, encoded string) bool {
	parts := strings.Split(encoded, "$")
	if len(parts) != 5 || parts[1] != "pbkdf2-sha256" {
		return false
	}
	rounds, err := strconv.Atoi(parts[2])
	if err != nil || rounds <= 0 || rounds > 10_000_000 {
		return false
	}
	salt, err := passlibEncoding.DecodeString(parts[3])
	if err != nil {
		return false
	}
	expected, err := passlibEncoding.DecodeString(parts[4])
	if err != nil || len(expected) != 32 {
		return false
	}
	actual := pbkdf2.Key([]byte(password), salt, rounds, 32, sha256.New)
	return subtle.ConstantTimeCompare(actual, expected) == 1
}
func HashPassword(password string) (string, error) {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	digest := pbkdf2.Key([]byte(password), salt, 29000, 32, sha256.New)
	return fmt.Sprintf("$pbkdf2-sha256$29000$%s$%s", passlibEncoding.EncodeToString(salt), passlibEncoding.EncodeToString(digest)), nil
}

type TokenData struct{ Subject, SessionID, TokenID uuid.UUID }
type TokenPair struct {
	TokenType    string `json:"tokenType"`
	AccessToken  string `json:"accessToken"`
	RefreshToken string `json:"refreshToken"`
}

func SignToken(cfg platform.Config, subject, sid, jti uuid.UUID, kind string, now time.Time) (string, error) {
	secret, ttl := cfg.AccessSecret, cfg.AccessTTL
	if kind == "refresh" {
		secret, ttl = cfg.RefreshSecret, cfg.RefreshTTL
	}
	method := jwt.GetSigningMethod(cfg.JWTAlgorithm)
	if _, ok := method.(*jwt.SigningMethodHMAC); !ok {
		return "", fmt.Errorf("unsupported JWT algorithm %q", cfg.JWTAlgorithm)
	}
	return jwt.NewWithClaims(method, jwt.MapClaims{"sub": subject.String(), "sid": sid.String(), "jti": jti.String(), "iat": now.Unix(), "nbf": now.Unix(), "exp": now.Add(ttl).Unix(), "type": kind}).SignedString([]byte(secret))
}
func DecodeToken(cfg platform.Config, raw, kind string) (TokenData, error) {
	var data TokenData
	secret := cfg.AccessSecret
	if kind == "refresh" {
		secret = cfg.RefreshSecret
	}
	token, err := jwt.Parse(raw, func(token *jwt.Token) (any, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("invalid signing method")
		}
		return []byte(secret), nil
	}, jwt.WithValidMethods([]string{cfg.JWTAlgorithm}), jwt.WithLeeway(5*time.Second), jwt.WithIssuedAt())
	if err != nil || !token.Valid {
		return data, fmt.Errorf("invalid token")
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok || claims["type"] != kind {
		return data, fmt.Errorf("invalid token type")
	}
	for key, destination := range map[string]*uuid.UUID{"sub": &data.Subject, "sid": &data.SessionID, "jti": &data.TokenID} {
		v, ok := claims[key].(string)
		if !ok {
			return data, fmt.Errorf("invalid token claims")
		}
		*destination, err = uuid.Parse(v)
		if err != nil {
			return data, err
		}
	}
	return data, nil
}
func Pair(cfg platform.Config, subject, sid, refreshJTI uuid.UUID) (TokenPair, error) {
	now := time.Now().UTC()
	access, err := SignToken(cfg, subject, sid, uuid.New(), "access", now)
	if err != nil {
		return TokenPair{}, err
	}
	refresh, err := SignToken(cfg, subject, sid, refreshJTI, "refresh", now)
	return TokenPair{"bearer", access, refresh}, err
}
