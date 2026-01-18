#!/bin/bash
# Deploy script for harness subjects
# Usage: ./scripts/deploy.sh <subject_name>

set -e

SUBJECT=$1

if [ -z "$SUBJECT" ]; then
    echo "Usage: $0 <subject_name>"
    echo "Available subjects:"
    ls -1 subjects/
    exit 1
fi

SUBJECT_DIR="subjects/$SUBJECT"

if [ ! -d "$SUBJECT_DIR" ]; then
    echo "Error: Subject '$SUBJECT' not found in subjects/"
    exit 1
fi

echo "Deploying subject: $SUBJECT"
echo "================================"

# Navigate to subject directory
cd "$SUBJECT_DIR"

# Check for pyproject.toml
if [ ! -f "pyproject.toml" ]; then
    echo "Error: No pyproject.toml found in $SUBJECT_DIR"
    exit 1
fi

# Install/upgrade the subject package
echo "Installing $SUBJECT package..."
pip install -e . --quiet

# Run tests if they exist
if [ -d "tests" ]; then
    echo "Running tests..."
    python -m pytest tests/ -v --tb=short
    if [ $? -ne 0 ]; then
        echo "Tests failed! Aborting deployment."
        exit 1
    fi
    echo "Tests passed!"
else
    echo "Warning: No tests directory found, skipping tests"
fi

# Check if service is already running (simple check)
RUNNING_PID=$(pgrep -f "${SUBJECT}.main" || true)

if [ -n "$RUNNING_PID" ]; then
    echo "Stopping existing $SUBJECT service (PID: $RUNNING_PID)..."
    kill $RUNNING_PID || true
    sleep 2
fi

# Start the service in background
echo "Starting $SUBJECT service..."
nohup python -m ${SUBJECT}.main > /tmp/${SUBJECT}.log 2>&1 &
NEW_PID=$!

# Wait a moment and check if it started
sleep 2

if ps -p $NEW_PID > /dev/null; then
    echo "Service started successfully (PID: $NEW_PID)"
    echo "Log file: /tmp/${SUBJECT}.log"
else
    echo "Error: Service failed to start"
    echo "Check log file: /tmp/${SUBJECT}.log"
    tail -20 /tmp/${SUBJECT}.log
    exit 1
fi

echo "================================"
echo "Deployment complete!"
