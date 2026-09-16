#!/usr/bin/env bash
# Create and verify the standard Gemini Developer API key used by Beckon.
# Deliberately does not create an authorization key bound to a service account.
set -euo pipefail

PROJECT="${BECKON_PROJECT_ID:-}"
ROTATE=false

usage() {
  cat <<'EOF'
Usage: beckon setup-api-key [--project PROJECT_ID] [--rotate]

Creates a standard API key restricted to generativelanguage.googleapis.com,
saves it to ~/.config/beckon/api_key with mode 0600, and verifies it.
--rotate replaces an existing key; otherwise a working key is kept.
EOF
}

while (($#)); do
  case "$1" in
    --project) PROJECT="${2:?--project needs a project ID}"; shift 2 ;;
    --rotate) ROTATE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v gcloud >/dev/null || { echo "Google Cloud CLI is required. Install google-cloud-cli, then run again." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }

if ! gcloud auth list --filter='status:ACTIVE' --format='value(account)' | grep -q .; then
  echo "Opening Google sign-in…"
  gcloud auth login
fi
if [[ -z "$PROJECT" ]]; then PROJECT="$(gcloud config get-value project 2>/dev/null || true)"; fi
if [[ -z "$PROJECT" || "$PROJECT" == "(unset)" ]]; then
  echo "No Google Cloud project selected. Run with --project PROJECT_ID." >&2; exit 2
fi

gcloud projects describe "$PROJECT" --format='value(projectId)' >/dev/null
echo "Using Google Cloud project: $PROJECT"
echo "Enabling Gemini Developer API…"
gcloud services enable generativelanguage.googleapis.com --project="$PROJECT"

CONFIG_DIR="$HOME/.config/beckon"
KEY_FILE="$CONFIG_DIR/api_key"
mkdir -p -m 700 "$CONFIG_DIR"

test_key() {
  local key response status
  key="$(tr -d '\r\n' < "$1")"
  if ! response="$(printf 'header = "x-goog-api-key: %s"\n' "$key" | curl --config - --silent --show-error --connect-timeout 10 --max-time 30 --write-out $'\n%{http_code}' 'https://generativelanguage.googleapis.com/v1beta/models')"; then
    echo "Could not reach the Gemini API." >&2
    return 1
  fi
  status="${response##*$'\n'}"
  if [[ "$status" == 200 ]]; then echo "Gemini API connection confirmed."; return 0; fi
  echo "Gemini API test failed (HTTP $status)." >&2
  case "$response" in
    *API_KEY_SERVICE_BLOCKED*) echo "The key does not allow the Gemini Developer API. Check its API restrictions." >&2 ;;
    *SERVICE_DISABLED*|*"has not been used"*) echo "The Gemini Developer API is not enabled yet; wait a moment and retry." >&2 ;;
    *API_KEY_INVALID*) echo "The stored key is invalid." >&2 ;;
  esac
  return 1
}

if [[ -f "$KEY_FILE" && "$ROTATE" == false ]]; then
  echo "A Beckon key already exists; testing it (use --rotate to replace it)…"
  test_key "$KEY_FILE" && exit 0
  echo "Existing key did not work; creating a replacement."
fi

echo "Creating a standard Gemini API key…"
KEY_NAME="$(gcloud services api-keys create --project="$PROJECT" --display-name=beckon-gemini --api-target=service=generativelanguage.googleapis.com --format='value(name)')"
if [[ -z "$KEY_NAME" ]]; then echo "Google Cloud did not return the new key ID." >&2; exit 1; fi
KEY="$(gcloud services api-keys get-key-string "$KEY_NAME" --format='value(keyString)')"
if [[ -z "$KEY" ]]; then echo "Could not retrieve the new key string ($KEY_NAME)." >&2; exit 1; fi
umask 077
TEMP_KEY="$(mktemp "$CONFIG_DIR/.api_key.XXXXXX")"
trap 'rm -f "$TEMP_KEY"' EXIT
printf '%s\n' "$KEY" > "$TEMP_KEY"
unset KEY
if ! test_key "$TEMP_KEY"; then
  echo "The previous local key was kept. The new cloud key is $KEY_NAME." >&2
  exit 1
fi
mv "$TEMP_KEY" "$KEY_FILE"
trap - EXIT
echo "Key saved securely to $KEY_FILE."
