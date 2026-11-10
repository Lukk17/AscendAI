#!/bin/sh
# Entry point of the prometheus service (task 13.11, design D16).
#
# Prometheus v2.55 expands environment variables only in external label
# values, never in the rest of its configuration file, so this script renders
# the committed template infra/observability/prometheus/prometheus.yaml by
# replacing exactly the four operational names with their environment values,
# records the per-provider token prices from pricing.yaml as the series
# token_price_usd_per_1k, checks the result with promtool, and starts
# Prometheus with its normal arguments. The rendered files live under
# /prometheus and are never committed.
set -eu

TEMPLATE=/etc/prometheus/prometheus.yaml
PRICING=/etc/prometheus/pricing.yaml
RENDERED=/prometheus/prometheus.yaml
RULES=/prometheus/token-price-rules.yaml

PROMETHEUS_SCRAPE_INTERVAL_VALUE="${PROMETHEUS_SCRAPE_INTERVAL:-15s}"
PROMETHEUS_EVALUATION_INTERVAL_VALUE="${PROMETHEUS_EVALUATION_INTERVAL:-15s}"
OBSERVABILITY_CLUSTER_LABEL_VALUE="${OBSERVABILITY_CLUSTER_LABEL:-ascend-ai-local}"
PROMETHEUS_QDRANT_TARGET_VALUE="${PROMETHEUS_QDRANT_TARGET:-host.docker.internal:6333}"

if [ ! -r "$PRICING" ]; then
  echo "price-rules.sh: pricing file $PRICING is missing or unreadable" >&2
  exit 1
fi

if [ ! -r "$TEMPLATE" ]; then
  echo "price-rules.sh: template $TEMPLATE is missing or unreadable" >&2
  exit 1
fi

awk \
  -v scrape="$PROMETHEUS_SCRAPE_INTERVAL_VALUE" \
  -v evaluation="$PROMETHEUS_EVALUATION_INTERVAL_VALUE" \
  -v cluster="$OBSERVABILITY_CLUSTER_LABEL_VALUE" \
  -v qdrant="$PROMETHEUS_QDRANT_TARGET_VALUE" \
  'function replace_all(line, placeholder, value, out, rest, at) {
     out = ""
     rest = line
     while ((at = index(rest, placeholder)) > 0) {
       out = out substr(rest, 1, at - 1) value
       rest = substr(rest, at + length(placeholder))
     }
     return out rest
   }
   {
     line = $0
     line = replace_all(line, "${PROMETHEUS_SCRAPE_INTERVAL}", scrape)
     line = replace_all(line, "${PROMETHEUS_EVALUATION_INTERVAL}", evaluation)
     line = replace_all(line, "${OBSERVABILITY_CLUSTER_LABEL}", cluster)
     line = replace_all(line, "${PROMETHEUS_QDRANT_TARGET}", qdrant)
     print line
   }' "$TEMPLATE" > "$RENDERED"

awk '
  /^[[:space:]]*(#.*)?$/ { next }
  /^[[:space:]]*providers:[[:space:]]*(#.*)?$/ { in_providers = 1; next }
  in_providers != 1 { print "price-rules.sh: line outside providers map: " $0 > "/dev/stderr"; exit 1 }
  /^  [A-Za-z0-9_.-]+:[[:space:]]*(#.*)?$/ {
    provider = $1
    sub(/:[[:space:]]*$/, "", provider)
    input_rate[provider] = ""
    output_rate[provider] = ""
    order[++count] = provider
    next
  }
  /^    (input_per_1k|output_per_1k):[[:space:]]+[^[:space:]#]+([[:space:]]*(#.*)?)?$/ {
    if (provider == "") { print "price-rules.sh: rate without provider: " $0 > "/dev/stderr"; exit 1 }
    key = $1
    sub(/:$/, "", key)
    value = $2
    if (value !~ /^[0-9]+(\.[0-9]+)?$/) { print "price-rules.sh: rate is not numeric: " $0 > "/dev/stderr"; exit 1 }
    if (key == "input_per_1k") { input_rate[provider] = value } else { output_rate[provider] = value }
    next
  }
  { print "price-rules.sh: cannot parse pricing line: " $0 > "/dev/stderr"; exit 1 }
  END {
    if (count == 0) { print "price-rules.sh: no providers in pricing file" > "/dev/stderr"; exit 1 }
    for (i = 1; i <= count; i++) {
      p = order[i]
      if (input_rate[p] == "" || output_rate[p] == "") {
        print "price-rules.sh: provider without both rates: " p > "/dev/stderr"
        exit 1
      }
    }
    print "groups:"
    print "  - name: token-prices"
    print "    rules:"
    for (i = 1; i <= count; i++) {
      p = order[i]
      printf "      - record: token_price_usd_per_1k\n        labels:\n          gen_ai_system: \"%s\"\n          gen_ai_token_type: \"input\"\n        expr: vector(%s)\n", p, input_rate[p]
      printf "      - record: token_price_usd_per_1k\n        labels:\n          gen_ai_system: \"%s\"\n          gen_ai_token_type: \"output\"\n        expr: vector(%s)\n", p, output_rate[p]
    }
  }
' "$PRICING" > "$RULES"

promtool check config "$RENDERED"

exec /bin/prometheus "$@"
