#! /bin/bash
end=$((SECONDS+3600))

while [ $SECONDS -lt $end ]; do
    python ../../../arat.py ../../../specs/eswagger/fdic.yaml http://localhost:9001/api
done
