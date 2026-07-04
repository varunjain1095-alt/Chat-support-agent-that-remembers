# Known Issues and Resolutions

## API Rate Limiting (Error 429) After Plan Upgrade
If a user upgrades their plan but continues to experience HTTP 429 (Rate Limiting) errors, it is likely due to a stale cache in the API client layer not recognizing the updated plan tier limits.

### Resolution Steps
To resolve this rate-limiting issue, direct the user through the following exact sequence:
1. Clear the API client's local cache.
2. Regenerate the API key from the customer dashboard under Settings > API Keys.
3. Update the regenerated API key in the environment variables or config file.
4. Re-run a test batch to confirm the new rate limit applies.
