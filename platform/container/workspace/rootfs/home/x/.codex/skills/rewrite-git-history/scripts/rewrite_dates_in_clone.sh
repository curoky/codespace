#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  rewrite_dates_in_clone.sh --repo PATH --output PATH [options]

Required:
  --repo PATH          Source Git repository (never modified)
  --output PATH        New clone path; must not exist

Options:
  --branch NAME        Branch to rewrite (default: current branch)
  --start YYYY-MM-DD   Start of date window (default: end minus 3 years)
  --end YYYY-MM-DD     End of date window (default: today)
  --timezone OFFSET    Git timezone offset (default: +0800)
  --seed INTEGER       Deterministic schedule seed (default: 27491)
  --active-days N      Active weekend days (default: about commits/4)
USAGE
}

repo=
output=
branch=
start=
end=$(date +%F)
timezone=+0800
seed=27491
active_days=

while (($#)); do
  case "$1" in
    --repo)
      repo=$2
      shift 2
      ;;
    --output)
      output=$2
      shift 2
      ;;
    --branch)
      branch=$2
      shift 2
      ;;
    --start)
      start=$2
      shift 2
      ;;
    --end)
      end=$2
      shift 2
      ;;
    --timezone)
      timezone=$2
      shift 2
      ;;
    --seed)
      seed=$2
      shift 2
      ;;
    --active-days)
      active_days=$2
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$repo" && -n "$output" ]] || {
  usage >&2
  exit 2
}
[[ -d "$repo/.git" ]] || {
  echo "not a Git worktree: $repo" >&2
  exit 1
}
[[ ! -e "$output" ]] || {
  echo "output already exists: $output" >&2
  exit 1
}
[[ "$timezone" =~ ^[+-][0-9]{4}$ ]] || {
  echo "timezone must look like +0800" >&2
  exit 2
}
[[ "$seed" =~ ^[0-9]+$ ]] || {
  echo "seed must be a non-negative integer" >&2
  exit 2
}
if ! git -C "$repo" diff --quiet || ! git -C "$repo" diff --cached --quiet; then
  echo "source repository has tracked changes" >&2
  exit 1
fi
branch=${branch:-$(git -C "$repo" symbolic-ref --quiet --short HEAD)}
git -C "$repo" rev-parse --verify "$branch^{commit}" >/dev/null
[[ $(git -C "$repo" rev-list --max-parents=0 --count "$branch") -eq 1 ]] || {
  echo "multiple roots are not supported" >&2
  exit 1
}
[[ $(git -C "$repo" rev-list --merges --count "$branch") -eq 0 ]] || {
  echo "merge history is not supported" >&2
  exit 1
}
[[ -z $(git -C "$repo" tag --merged "$branch") ]] || {
  echo "tags point into the rewritten history; handle them explicitly" >&2
  exit 1
}
while read -r commit; do
  if git -C "$repo" cat-file commit "$commit" | sed -n '/^$/q; /^gpgsig /p' | grep -q .; then
    echo "signed commit is not supported: $commit" >&2
    exit 1
  fi
done < <(git -C "$repo" rev-list "$branch")

start=${start:-$(date -d "$end - 3 years" +%F)}
date -d "$start" +%F >/dev/null
date -d "$end" +%F >/dev/null
[[ "$start" < "$end" ]] || {
  echo "start must be before end" >&2
  exit 2
}

original_tree=$(git -C "$repo" rev-parse "$branch^{tree}")
git clone --no-local --single-branch --branch "$branch" "$repo" "$output" >/dev/null
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
commits=$(git -C "$output" rev-list --count "$branch")

first=$start
while [[ $(date -d "$first" +%u) -ne 6 ]]; do first=$(date -d "$first + 1 day" +%F); done
: >"$work/saturdays"
d=$first
while [[ $(date -d "$d + 1 day" +%F) < "$end" || $(date -d "$d + 1 day" +%F) == "$end" ]]; do
  printf '%s\n' "$d" >>"$work/saturdays"
  d=$(date -d "$d + 7 days" +%F)
done
weeks=$(wc -l <"$work/saturdays")
((weeks > 0)) || {
  echo "date range contains no complete weekend" >&2
  exit 1
}
weekend_days=$((weeks * 2))

if [[ -z "$active_days" ]]; then
  active_days=$(((commits + 3) / 4))
  minimum=$(((commits + 6) / 7))
  maximum=$((weekend_days * 35 / 100))
  ((active_days < minimum)) && active_days=$minimum
  ((maximum > 0 && active_days > maximum)) && active_days=$maximum
fi
[[ "$active_days" =~ ^[1-9][0-9]*$ ]] || {
  echo "active-days must be positive" >&2
  exit 2
}
((active_days <= commits)) || active_days=$commits
((active_days <= weekend_days)) || {
  echo "not enough weekend days in range" >&2
  exit 1
}
((commits <= active_days * 7)) || {
  echo "active-days is too small for the seven-commit daily cap" >&2
  exit 1
}

dual=$((active_days / 8))
active_weeks=$((active_days - dual))
((active_weeks <= weeks)) || {
  echo "not enough weeks in range" >&2
  exit 1
}
runs=$(((active_weeks + 2) / 3))
((runs < 1)) && runs=1
((runs > active_weeks)) && runs=$active_weeks
awk -v n="$runs" 'BEGIN{for(i=1;i<=n;i++)print 1}' >"$work/run-lengths"
remaining=$((active_weeks - runs))
rng=$seed
while ((remaining > 0)); do
  rng=$(((rng * 1103515245 + 12345) & 2147483647))
  row=$((rng % runs + 1))
  value=$(sed -n "$row p" "$work/run-lengths")
  if ((value < 4)); then
    awk -v row="$row" 'NR==row{$1++}{print}' "$work/run-lengths" >"$work/next"
    mv "$work/next" "$work/run-lengths"
    remaining=$((remaining - 1))
  fi
done

gap_slots=$((runs + 1))
awk -v n="$gap_slots" 'BEGIN{for(i=1;i<=n;i++)print (i==1||i==n)?0:1}' >"$work/gaps"
remaining=$((weeks - active_weeks - runs + 1))
while ((remaining > 0)); do
  rng=$(((rng * 1103515245 + 12345) & 2147483647))
  row=$((rng % gap_slots + 1))
  value=$(sed -n "$row p" "$work/gaps")
  cap=5
  ((row == 1 || row == gap_slots)) && cap=4
  if ((value < cap)); then
    awk -v row="$row" 'NR==row{$1++}{print}' "$work/gaps" >"$work/next"
    mv "$work/next" "$work/gaps"
    remaining=$((remaining - 1))
  elif ! awk '$1<5{found=1}END{exit !found}' "$work/gaps"; then
    awk -v row="$row" 'NR==row{$1++}{print}' "$work/gaps" >"$work/next"
    mv "$work/next" "$work/gaps"
    remaining=$((remaining - 1))
  fi
done

: >"$work/active-week-indexes"
week_index=$(sed -n '1p' "$work/gaps")
for ((run = 1; run <= runs; run++)); do
  length=$(sed -n "$run p" "$work/run-lengths")
  for ((j = 0; j < length; j++)); do echo $((week_index + j)) >>"$work/active-week-indexes"; done
  week_index=$((week_index + length + $(sed -n "$((run + 1))p" "$work/gaps")))
done

: >"$work/scored-weeks"
while read -r index; do
  rng=$(((rng * 1103515245 + 12345) & 2147483647))
  printf '%010d %d\n' "$rng" "$index" >>"$work/scored-weeks"
done <"$work/active-week-indexes"
sort -n "$work/scored-weeks" | head -n "$dual" | awk '{print $2}' | sort -n >"$work/dual-weeks" || true

: >"$work/active-days"
while read -r index; do
  saturday=$(sed -n "$((index + 1))p" "$work/saturdays")
  sunday=$(date -d "$saturday + 1 day" +%F)
  if grep -qx "$index" "$work/dual-weeks"; then
    printf '%s\n%s\n' "$saturday" "$sunday" >>"$work/active-days"
  else
    rng=$(((rng * 1103515245 + 12345) & 2147483647))
    if ((rng % 100 < 70)); then printf '%s\n' "$saturday" >>"$work/active-days"; else printf '%s\n' "$sunday" >>"$work/active-days"; fi
  fi
done <"$work/active-week-indexes"
sort -u "$work/active-days" -o "$work/active-days"
[[ $(wc -l <"$work/active-days") -eq "$active_days" ]]

awk '{print $0,1}' "$work/active-days" >"$work/day-counts"
remaining=$((commits - active_days))
while ((remaining > 0)); do
  rng=$(((rng * 1103515245 + 12345) & 2147483647))
  row=$((rng % active_days + 1))
  value=$(sed -n "$row p" "$work/day-counts" | awk '{print $2}')
  if ((value < 7)); then
    awk -v row="$row" 'NR==row{$2++}{print}' "$work/day-counts" >"$work/next"
    mv "$work/next" "$work/day-counts"
    remaining=$((remaining - 1))
  fi
done

: >"$work/dates"
while read -r day count; do
  rng=$(((rng * 1103515245 + 12345) & 2147483647))
  minute=$((540 + rng % 301))
  for ((j = 1; j <= count; j++)); do
    if ((j > 1)); then
      rng=$(((rng * 1103515245 + 12345) & 2147483647))
      minute=$((minute + 11 + rng % 85))
    fi
    ((minute <= 1410)) || {
      echo "generated session crossed 23:30; choose another seed" >&2
      exit 1
    }
    rng=$(((rng * 1103515245 + 12345) & 2147483647))
    printf '%s %02d:%02d:%02d %s\n' "$day" "$((minute / 60))" "$((minute % 60))" "$((rng % 60))" "$timezone" >>"$work/dates"
  done
done <"$work/day-counts"

paste <(git -C "$output" rev-list --reverse "$branch") "$work/dates" >"$work/rewrite-input"
parent=
while IFS=$'\t' read -r old new_date; do
  tree=$(git -C "$output" rev-parse "$old^{tree}")
  git -C "$output" show -s --format=%B "$old" >"$work/message"
  env_args=(
    "GIT_AUTHOR_NAME=$(git -C "$output" show -s --format=%an "$old")"
    "GIT_AUTHOR_EMAIL=$(git -C "$output" show -s --format=%ae "$old")"
    "GIT_AUTHOR_DATE=$new_date"
    "GIT_COMMITTER_NAME=$(git -C "$output" show -s --format=%cn "$old")"
    "GIT_COMMITTER_EMAIL=$(git -C "$output" show -s --format=%ce "$old")"
    "GIT_COMMITTER_DATE=$new_date"
  )
  if [[ -n "$parent" ]]; then
    parent=$(env "${env_args[@]}" git -C "$output" commit-tree "$tree" -p "$parent" <"$work/message")
  else
    parent=$(env "${env_args[@]}" git -C "$output" commit-tree "$tree" <"$work/message")
  fi
done <"$work/rewrite-input"

git -C "$output" update-ref "refs/heads/$branch" "$parent"
git -C "$output" reset --hard "$branch" >/dev/null
printf '' | git -C "$output" hash-object -t tree -w --stdin >/dev/null
git -C "$output" fsck --full --no-dangling
[[ $(git -C "$output" rev-parse "$branch^{tree}") == "$original_tree" ]]

printf 'rewritten_repo=%s\nbranch=%s\ntip=%s\ncommits=%s\nactive_days=%s\nactive_weeks=%s\n' \
  "$output" "$branch" "$parent" "$commits" "$active_days" "$active_weeks"
echo 'commits_per_active_day:'
awk '{hist[$2]++}END{for(n in hist)print "  " n ": " hist[n]}' "$work/day-counts" | sort -n
echo 'date_range:'
git -C "$output" log --reverse --format='  first=%aI' | sed -n '1p'
git -C "$output" log -1 --format='  last=%aI'
