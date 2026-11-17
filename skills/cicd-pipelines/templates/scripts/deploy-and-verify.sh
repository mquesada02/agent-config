#!/usr/bin/env bash
# Deploy the stored zip of a commit, then check that the live version is that commit.
# Usage: deploy-and-verify.sh <bucket> <sha> <function> <version_url>
# DEPLOY_TARGET picks the deploy step (lambda or terraform). VERIFY_TRIES and VERIFY_PAUSE tune the version check.
set -euo pipefail

bucket="${1:-}"
sha="${2:-}"
function_name="${3:-}"
version_url="${4:-}"
target="${DEPLOY_TARGET:-lambda}"
tries="${VERIFY_TRIES:-6}"
pause="${VERIFY_PAUSE:-10}"

require() {
  if [ -z "$2" ]; then
    echo "::error::The setting $1 is empty, so the deploy cannot run"
    exit 1
  fi
}
require bucket "$bucket"
require sha "$sha"
require function "$function_name"
require version_url "$version_url"

# The digest check: prod and rollback deploy only the zip that the package job stored.
aws s3 cp "s3://$bucket/$sha/app.zip" app.zip
aws s3 cp "s3://$bucket/$sha/app.zip.sha256" app.zip.sha256
actual="$(sha256sum app.zip | cut -d' ' -f1)"
expected="$(cat app.zip.sha256)"
if [ "$actual" != "$expected" ]; then
  echo "::error::The digest of app.zip is $actual, not the stored $expected"
  exit 1
fi

case "$target" in
  lambda)
    aws lambda update-function-code --function-name "$function_name" --zip-file fileb://app.zip > /dev/null
    aws lambda wait function-updated --function-name "$function_name"
    version="$(aws lambda publish-version --function-name "$function_name" --description "$sha" --query Version --output text)"
    aws lambda update-alias --function-name "$function_name" --name live --function-version "$version" > /dev/null
    ;;
  terraform)
    terraform plan -input=false -var "zip_path=$PWD/app.zip"
    terraform apply -input=false -auto-approve -var "zip_path=$PWD/app.zip"
    ;;
  *)
    echo "::error::The deploy target $target is not lambda or terraform"
    exit 1
    ;;
esac

# The version check: an old version that answers 200 must not pass.
for _ in $(seq "$tries"); do
  if curl -fsS "$version_url" | grep -qF "$sha"; then
    exit 0
  fi
  sleep "$pause"
done
echo "::error::The live version is not $sha"
exit 1
