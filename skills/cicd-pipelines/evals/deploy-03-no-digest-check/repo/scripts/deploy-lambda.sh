#!/usr/bin/env bash
set -euo pipefail
bucket="$1"
sha="$2"
function_name="$3"
version_url="$4"
aws s3 cp "s3://$bucket/$sha/app.zip" app.zip
version="$(aws lambda update-function-code --function-name "$function_name" --zip-file fileb://app.zip --publish --query Version --output text)"
aws lambda update-alias --function-name "$function_name" --name live --function-version "$version"
for attempt in 1 2 3 4 5; do
  if curl -fsS "$version_url" | grep -q "$sha"; then
    exit 0
  fi
  sleep 10
done
echo "::error::The live version is not $sha"
exit 1
