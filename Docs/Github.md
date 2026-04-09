## How to access customer's Repo


- First they have to install it (Not figured out full flow just yet)

- Generate JWT with the app's pem file

- Access all installations with: 
```bash
curl --request GET \
--url "https://api.github.com/app/installations" \
--header "Accept: application/vnd.github+json" \
--header "Authorization: Bearer ${JWT}" \
--header "X-GitHub-Api-Version: 2026-03-10"
```

-  Get installation id with the `id` variable for each element in the list with their account

- Generate installation access token:
```bash
curl -X POST \
     -H "Accept: application/vnd.github+json" \
     -H "Authorization: Bearer ${JWT}" \
     https://api.github.com/app/installations/${INSTALLATION_ID}/access_tokens
```

- Use token to get repo data:
```bash
 curl -L \
     -H "Accept: application/vnd.github.object" \
     -H "Authorization: Bearer ${INSTALLATION_TOKEN}" \
     -H "X-GitHub-Api-Version: 2022-11-28" \
     https://api.github.com/repos/skb231/OpenSur/contents/
```