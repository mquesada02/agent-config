#!/usr/bin/env bash
set -euo pipefail
bucket="$1"
sha="$2"
function_name="$3"
version_url="$4"
aws s3 cp "s3://$bucket/$sha/app.zip" app.zip
aws s3 cp "s3://$bucket/$sha/app.zip.sha256" app.zip.sha256
test "$(sha256sum app.zip | cut -d' ' -f1)" = "$(cat app.zip.sha256)"
version="$(aws lambda update-function-code --function-name "$function_name" --zip-file fileb://app.zip --publish --query Version --output text)"
aws lambda update-alias --function-name "$function_name" --name live --function-version "$version"
curl -fsS "$version_url" > /dev/null
