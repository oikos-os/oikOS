#!/bin/bash
set -e
echo "=== Docker Rooms Smoke Test ==="

docker compose up -d
sleep 15

echo "--- Create Room ---"
curl -sf -X POST http://localhost:8420/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"id": "docker-test", "name": "Docker Test", "toolsets": ["vault"]}'

echo "--- Switch Room ---"
curl -sf -X POST http://localhost:8420/api/rooms/switch \
  -H "Content-Type: application/json" \
  -d '{"room_id": "docker-test"}'

echo "--- Verify Active ---"
ACTIVE=$(curl -sf http://localhost:8420/api/rooms/active | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
[ "$ACTIVE" = "docker-test" ] && echo "PASS: Active room correct" || { echo "FAIL: Active room is $ACTIVE"; exit 1; }

echo "--- Restart Stack ---"
docker compose down
docker compose up -d
sleep 15

echo "--- Verify Persistence ---"
ACTIVE=$(curl -sf http://localhost:8420/api/rooms/active | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
[ "$ACTIVE" = "docker-test" ] && echo "PASS: Room persisted across restart" || { echo "FAIL: Room lost"; exit 1; }

echo "--- Cleanup ---"
curl -sf -X DELETE http://localhost:8420/api/rooms/docker-test
docker compose down
echo "=== All Docker Smoke Tests PASSED ==="
