#! /bin/bash
end=$((SECONDS+3600))

while [ $SECONDS -lt $end ]; do
    schemathesis run ../../../specs/openapi_json/spotify.json --hypothesis-database=none --checks all --stateful=links --max-response-time=30000 --validate-schema False --base-url http://localhost:9008/v1
    schemathesis run ../../../specs/openapi_json/spotify.json --hypothesis-database=none --stateful=links --max-response-time=30000 --validate-schema False --base-url http://localhost:9008/v1
done
