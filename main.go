package main

import (
	"fmt"
	"os"

	"github.com/SKB231/deploymouse/internal/github"
	"github.com/joho/godotenv"
)

const pemPath string = "./dm.pem"

func main() {
	godotenv.Load()
	appID := os.Getenv("GITHUB_APP_ID")
	jwtToken, err := github.GenerateJWT(appID, pemPath)
	if err != nil {
		fmt.Println("error when generating key:", err)
		return
	}

	installationID, err := github.GetInstallationID(jwtToken)
	if err != nil {
		fmt.Println("error getting installation ID:", err)
		return
	}

	token, err := github.GetInstallationToken(jwtToken, installationID)
	if err != nil {
		fmt.Println("error getting installation token:", err)
		return
	}
	fmt.Println(token)

	data, err := github.GetRepoContents(token, "skb231", "OpenSur", "")
	if err != nil {
		fmt.Println("error getting repo contents:", err)
		return
	}
	fmt.Println(string(data))
}
