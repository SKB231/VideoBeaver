package github

import (
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func GenerateJWT(appID, pemPath string) (string, error) {
	file, err := os.Open(pemPath)
	if err != nil {
		return "", err
	}

	privateKeyPEM, err := io.ReadAll(file)
	if err != nil {
		return "", err
	}

	block, _ := pem.Decode(privateKeyPEM)
	privateKey, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err != nil {
		return "", err
	}

	now := time.Now()
	claims := jwt.MapClaims{
		"iat": now.Add(-60 * time.Second).Unix(), // issued slightly in the past (clock skew)
		"exp": now.Add(10 * time.Minute).Unix(),  // max 10 min
		"iss": appID,
	}

	token := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	return token.SignedString(privateKey)
}

func GetInstallationID(jwtToken string) (int, error) {
	req, err := http.NewRequest("GET", "https://api.github.com/app/installations", nil)
	if err != nil {
		return 0, err
	}
	req.Header.Add("Authorization", fmt.Sprintf("Bearer %v", jwtToken))

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, err
	}

	var respJson []struct {
		Id int `json:"id"`
	}
	if err = json.Unmarshal(respBody, &respJson); err != nil {
		return 0, err
	}

	return respJson[0].Id, nil
}

func GetInstallationToken(jwtToken string, installationID int) (string, error) {
	req, err := http.NewRequest("POST", fmt.Sprintf("https://api.github.com/app/installations/%v/access_tokens", installationID), nil)
	if err != nil {
		return "", err
	}
	req.Header.Add("Authorization", fmt.Sprintf("Bearer %v", jwtToken))

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	var tokenStruct struct {
		Token string `json:"token"`
	}
	if err = json.Unmarshal(respBody, &tokenStruct); err != nil {
		return "", err
	}

	return tokenStruct.Token, nil
}

func GetRepoContents(token, owner, repo, path string) ([]byte, error) {
	req, err := http.NewRequest("GET", fmt.Sprintf("https://api.github.com/repos/%v/%v/contents/%v", owner, repo, path), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Add("Authorization", fmt.Sprintf("Bearer %v", token))

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}

	return io.ReadAll(resp.Body)
}
