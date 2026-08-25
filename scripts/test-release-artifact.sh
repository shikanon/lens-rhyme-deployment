#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/release-artifact.sh"

sha="0123456789abcdef0123456789abcdef01234567"
[[ "$(canonical_artifact_tag "$sha" 1 overseas)" == "git-${sha}" ]]
[[ "$(canonical_artifact_tag "$sha" 2 overseas)" == "git-${sha}-r2" ]]
[[ "$(canonical_artifact_tag "$sha" 2 china registry.cn-hangzhou.aliyuncs.com/lens-rhyme)" == "git-${sha}-r2" ]]
[[ "$(canonical_artifact_tag "$sha" 2 china shikanon096)" == "git-${sha}-r2-cn" ]]
if canonical_artifact_tag 0123456 1 overseas >/dev/null 2>&1; then
  echo "short SHA was accepted" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
cat >"${tmp_dir}/docker" <<'EOF'
#!/usr/bin/env bash
case "${FAKE_DOCKER_RESULT:-exists}" in
  exists)
    echo 'Name: example/image'
    echo 'Digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    ;;
  missing)
    echo 'ERROR: manifest unknown' >&2
    exit 1
    ;;
  auth)
    echo 'ERROR: unauthorized: authentication required' >&2
    exit 1
    ;;
esac
EOF
chmod +x "${tmp_dir}/docker"
PATH="${tmp_dir}:$PATH"

[[ "$(FAKE_DOCKER_RESULT=exists probe_release_image example/image:tag)" == "exists sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" ]]
set +e
missing="$(FAKE_DOCKER_RESULT=missing probe_release_image example/image:tag)"; missing_status=$?
auth="$(FAKE_DOCKER_RESULT=auth probe_release_image example/image:tag)"; auth_status=$?
set -e
[[ "$missing" == missing && "$missing_status" -eq 1 ]]
[[ "$auth" == error* && "$auth_status" -eq 3 ]]

release_file="${tmp_dir}/release.env"
FAKE_DOCKER_RESULT=exists resolve_release_images registry.example/ns tag "$release_file"
[[ "$(wc -l <"$release_file" | tr -d ' ')" -eq 6 ]]
grep -Fq 'CODEX_RUNNER_IMAGE=registry.example/ns/lens-rhyme-codex-runner@sha256:' "$release_file"
grep -Fq 'CONTENT_FRONTEND_IMAGE=registry.example/ns/lens-rhyme-content-frontend@sha256:' "$release_file"

echo "release artifact tests passed"
